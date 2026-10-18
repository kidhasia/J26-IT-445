"""Lab report pipeline: local OCR, then field parsing. No interpretation of results."""

from dataclasses import replace

from lumi.errors import LumiError
from lumi.pipelines.base import Pipeline, PipelineOutput
from lumi.pipelines.mock import UNANSWERED_QUESTION_WARNING, MockPipeline
from lumi.pipelines.ocr.engine import OcrEngine, OcrFailedError, OcrUnavailableError
from lumi.pipelines.ocr.parser import DEFAULT_REVIEW_CONFIDENCE, parse_lab_fields
from lumi.schemas import ErrorCode, InputType
from lumi.validation import ValidatedFile

REFERENCE_RANGE_NOTE = (
    "Reference ranges are copied exactly as printed on the report. They depend on the issuing "
    "laboratory and the patient's age, and LUMI does not judge whether any result is normal or abnormal."
)
OCR_NOT_VALIDATED_WARNING = (
    "OCR_NOT_VALIDATED: OCR accuracy has only been measured on a few clean synthetic reports (docs/OCR_EVALUATION.md) "
    "and has not been validated on real reports. Check every value against the original report."
)
NO_TEXT_WARNING = "NO_TEXT_FOUND: OCR found no readable text in this image."
NO_FIELDS_WARNING = "NO_FIELDS_PARSED: text was extracted but no test-result rows were recognised; see extracted_text."
PDF_NOT_SUPPORTED_WARNING = "PDF_OCR_NOT_IMPLEMENTED: PDF lab reports are accepted but not analysed yet; upload a PNG or JPEG image."


class LabReportOcrPipeline:
    name = "lab_report_ocr"

    def __init__(self, engine: OcrEngine, review_confidence: float = DEFAULT_REVIEW_CONFIDENCE):
        self._engine = engine
        self._review_confidence = review_confidence
        self._pdf_fallback: Pipeline = MockPipeline(InputType.LAB_REPORT)

    def run(self, file: ValidatedFile, question: str | None) -> PipelineOutput:
        if file.mime_type == "application/pdf":
            fallback = self._pdf_fallback.run(file, question)
            return replace(fallback, warnings=[*fallback.warnings, PDF_NOT_SUPPORTED_WARNING])

        try:
            ocr = self._engine.extract(file.data)
        except OcrUnavailableError as exc:
            raise LumiError(503, ErrorCode.OCR_UNAVAILABLE, f"OCR is temporarily unavailable: {exc}") from exc
        except OcrFailedError as exc:
            raise LumiError(500, ErrorCode.INTERNAL_ERROR, "OCR processing failed.") from exc

        fields = parse_lab_fields(ocr.lines, self._review_confidence)
        needing_review = sum(field.needs_review for field in fields)

        warnings = [OCR_NOT_VALIDATED_WARNING]
        if not ocr.lines:
            warnings.append(NO_TEXT_WARNING)
        elif not fields:
            warnings.append(NO_FIELDS_WARNING)
        if needing_review:
            warnings.append(
                f"FIELDS_NEED_REVIEW: {needing_review} of {len(fields)} parsed row(s) have missing parts "
                "or low OCR confidence."
            )
        if question is not None:
            warnings.append(UNANSWERED_QUESTION_WARNING)

        return PipelineOutput(
            result={
                "status": "completed",
                "pipeline": self.name,
                "engine": {"name": ocr.engine_name, "version": ocr.engine_version, "language": ocr.language},
                "extracted_text": ocr.text,
                "mean_ocr_confidence": ocr.mean_confidence,
                "fields": [field.to_dict() for field in fields],
                "fields_needing_review": needing_review,
                "reference_range_note": REFERENCE_RANGE_NOTE,
            },
            # The envelope's `confidence` is reserved for model predictions; OCR confidence is a
            # different quantity, so it is reported per line inside `result` instead.
            confidence=None,
            explanation=(
                "Text was extracted on this server with Tesseract OCR, and result rows were found by pattern "
                "matching. Each field gives the line it came from (line_number, source_text) so it can be checked "
                "against the original report. OCR can misread characters."
            ),
            warnings=warnings,
        )
