"""Router/service layer: picks the pipeline for an input type and builds the shared response."""

from collections.abc import Mapping

from lumi.config import CLINICAL_BOUNDARY_NOTICE
from lumi.pipelines.base import Pipeline
from lumi.pipelines.mock import MockPipeline
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

    def analyze(
        self,
        request_id: str,
        input_type: InputType,
        file: ValidatedFile,
        question: str | None,
        metadata: RequestMetadata | None,
    ) -> AnalyzeResponse:
        # metadata is accepted for future audit logging; it is not used by any pipeline.
        output = self.pipeline_for(input_type).run(file, question)
        return AnalyzeResponse(
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


def build_default_service() -> AnalysisService:
    return AnalysisService({input_type: MockPipeline(input_type) for input_type in InputType})
