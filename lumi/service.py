"""Router/service layer: picks the pipeline for an input type and builds the shared response."""

import json
from collections.abc import Mapping
from dataclasses import replace

from lumi.config import CLINICAL_BOUNDARY_NOTICE, Settings
from lumi.logging_config import logger
from lumi.pipelines.base import Pipeline
from lumi.pipelines.mock import UNANSWERED_QUESTION_WARNING
from lumi.qa.answerer import answer_question
from lumi.qa.evidence import EvidenceError, parse_evidence
from lumi.pipelines.mock import MockPipeline
from lumi.pipelines.unavailable import ModelUnavailablePipeline
from lumi.pipelines.ocr.engine import TesseractEngine
from lumi.pipelines.ocr.pipeline import LabReportOcrPipeline
from lumi.schemas import AnalyzeResponse, InputType, RequestMetadata
from lumi.validation import ValidatedFile


class AnalysisService:
    def __init__(self, pipelines: Mapping[InputType, Pipeline]):
        missing = set(InputType) - set(pipelines)
        if missing:
            raise ValueError(f"No pipeline registered for: {sorted(t.value for t in missing)}")
        self._pipelines = dict(pipelines)

    def pipeline_for(self, input_type: InputType) -> Pipeline:
        return self._pipelines[input_type]

    def model_summaries(self) -> dict[str, dict]:
        """Facts about trained models that are loaded, keyed by input type. Pipelines without a model are left out."""
        summaries: dict[str, dict] = {}
        for input_type, pipeline in self._pipelines.items():
            describe = getattr(pipeline, "model_info", None)
            if callable(describe):
                summaries[input_type.value] = describe()
        return summaries

    def statuses(self) -> dict[str, str]:
        """ready / placeholder (no real analysis) / unavailable (model not set up), per input type."""
        return {t.value: getattr(p, "status", "ready") for t, p in self._pipelines.items()}

    def analyze(
        self,
        request_id: str,
        input_type: InputType,
        file: ValidatedFile,
        question: str | None,
        metadata: RequestMetadata | None,
        explain: bool = False,
    ) -> AnalyzeResponse:
        # metadata is accepted for future audit logging; it is not used by any pipeline.
        pipeline = self.pipeline_for(input_type)
        if explain and getattr(pipeline, "supports_explanation", False):
            output = pipeline.run(file, question, explain=True)
        else:
            output = pipeline.run(file, question)
            if explain:
                output = replace(output, warnings=[*output.warnings, EXPLANATION_NOT_AVAILABLE_WARNING])
        response = AnalyzeResponse(
            request_id=request_id,
            input_type=input_type,
            result=output.result,
            confidence=output.confidence,
            answer=output.answer,
            explanation=output.explanation,
            xai_reference=output.xai_reference,
            warnings=list(output.warnings),
            clinical_boundary_notice=CLINICAL_BOUNDARY_NOTICE,
        )
        if question is not None:
            response = self._answer_from_own_result(response, question)
        return response

    @staticmethod
    def _answer_from_own_result(response: AnalyzeResponse, question: str) -> AnalyzeResponse:
        """One request, one answer: the question is answered from the result this same request just produced, with the
        same rules as POST /api/v1/ask (see lumi/qa). It never uses anything else. If there is no completed result to
        answer from (placeholder pipeline, nothing read), the answer stays empty and the 'not answered' warning stays."""
        if response.input_type == InputType.CHEST_XRAY or not response.result or response.result.get("status") != "completed":
            return response
        try:
            evidence = parse_evidence(response.model_dump(mode="json"))
        except EvidenceError:
            return response  # the result is not usable as evidence, so say nothing rather than guess
        answer = answer_question(question, evidence)
        warnings = [w for w in response.warnings if w != UNANSWERED_QUESTION_WARNING]
        return response.model_copy(update={
            "answer": answer.text,
            "explanation": response.explanation if answer.answerable else (response.explanation or answer.note),
            "warnings": warnings,
        })


EXPLANATION_NOT_AVAILABLE_WARNING = (
    "EXPLANATION_NOT_AVAILABLE: attention maps exist only for skin photos analysed by the trained model; "
    "none was made for this input."
)
SKIN_NOT_CONFIGURED = (
    "The skin-lesion model is not set up on this server (LUMI_SKIN_MODEL_PATH is not set), so no analysis was performed."
)
SKIN_LOAD_FAILED = "The skin-lesion model could not be loaded on this server, so no analysis was performed."


def build_skin_pipeline(settings: Settings | None) -> Pipeline:
    """A working classifier if a valid checkpoint is configured; otherwise a pipeline that answers 503.
    Never falls back to inventing a prediction."""
    path = settings.skin_model_path if settings else None
    if not path:
        return ModelUnavailablePipeline("skin_lesion_classifier", SKIN_NOT_CONFIGURED)
    try:
        from lumi.pipelines.skin.pipeline import SkinClassifierPipeline  # imports torch, so only when configured

        return SkinClassifierPipeline(path)
    except Exception as exc:  # noqa: BLE001
        # Log only the exception type: messages can include file paths.
        logger.error(json.dumps({"event": "skin_model_load_failed", "type": type(exc).__name__}))
        return ModelUnavailablePipeline("skin_lesion_classifier", SKIN_LOAD_FAILED)


def build_default_service(settings: Settings | None = None) -> AnalysisService:
    return AnalysisService(
        {
            InputType.SKIN_IMAGE: build_skin_pipeline(settings),
            InputType.CHEST_XRAY: MockPipeline(InputType.CHEST_XRAY),
            InputType.LAB_REPORT: LabReportOcrPipeline(TesseractEngine()),
        }
    )
