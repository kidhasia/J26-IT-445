"""Check that the supplied evidence really is a completed LUMI skin-photo or lab-report analysis.

Only the fields the answerer needs are read; everything else (such as the attention-map image data) is ignored.
Size limits keep a malicious or broken payload from causing trouble. Problems are reported by field PATH only, never
by value, so a rejected report's contents are not echoed back.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

SHORT = 200
TEXT = 2000
MAX_LIST = 200


class EvidenceError(Exception):
    """The evidence is missing, malformed, not completed, or not a kind this feature can answer from."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


# ---------------------------------------------------------------- skin


class ProbabilityItem(_Model):
    code: str = Field(alias="class", max_length=32)
    name: str = Field(max_length=SHORT)
    probability: float = Field(ge=0.0, le=1.0)


class ModelInfo(_Model):
    name: str | None = Field(default=None, max_length=SHORT)
    run_id: str | None = Field(default=None, max_length=SHORT)
    trained_on: dict[str, Any] | None = None
    evaluation: dict[str, Any] | None = None


class AttentionMapInfo(_Model):
    method: str | None = Field(default=None, max_length=SHORT)
    target_class: str | None = Field(default=None, max_length=32)
    target_class_name: str | None = Field(default=None, max_length=SHORT)
    target_layer: str | None = Field(default=None, max_length=SHORT)
    map_cells: list[int] | None = Field(default=None, max_length=2)


class SkinResult(_Model):
    status: Literal["completed"]
    pipeline: Literal["skin_lesion_classifier"]
    predicted_class: str = Field(max_length=32)
    predicted_class_name: str = Field(max_length=SHORT)
    probabilities: list[ProbabilityItem] = Field(min_length=1, max_length=30)
    limitations: list[str] = Field(default_factory=list, max_length=30)
    model: ModelInfo | None = None
    explanation_image: AttentionMapInfo | None = None  # only its description is read, never the image data


# ---------------------------------------------------------------- lab report


class LabField(_Model):
    test_name: str = Field(max_length=SHORT)
    value: str | None = Field(default=None, max_length=100)
    unit: str | None = Field(default=None, max_length=100)
    reference_range: str | None = Field(default=None, max_length=100)
    missing_fields: list[str] = Field(default_factory=list, max_length=3)
    needs_review: bool = False
    line_number: int = Field(default=0, ge=0, le=100000)
    ocr_confidence: float | None = Field(default=None, ge=0, le=100)


class LabResult(_Model):
    status: Literal["completed"]
    pipeline: Literal["lab_report_ocr"]
    fields: list[LabField] = Field(max_length=MAX_LIST)
    fields_needing_review: int = Field(default=0, ge=0)
    mean_ocr_confidence: float | None = Field(default=None, ge=0, le=100)
    reference_range_note: str | None = Field(default=None, max_length=TEXT)


# ---------------------------------------------------------------- whole analysis responses


class _Analysis(_Model):
    warnings: list[str] = Field(default_factory=list, max_length=30)
    clinical_boundary_notice: str | None = Field(default=None, max_length=TEXT)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    error: None = None  # an analysis that ended in an error is not evidence


class SkinEvidence(_Analysis):
    input_type: Literal["skin_image"]
    result: SkinResult


class LabEvidence(_Analysis):
    input_type: Literal["lab_report"]
    result: LabResult


Evidence = SkinEvidence | LabEvidence

GENERIC_MESSAGE = (
    "The evidence must be the JSON returned by POST /api/v1/analyze for a completed skin-photo or lab-report analysis."
)


def parse_evidence(raw: Any) -> Evidence:
    """Validate the supplied evidence. Raises EvidenceError with a message that names fields but never shows values."""
    if not isinstance(raw, dict):
        raise EvidenceError(GENERIC_MESSAGE)
    kind = raw.get("input_type")
    model = {"skin_image": SkinEvidence, "lab_report": LabEvidence}.get(kind) if isinstance(kind, str) else None
    if model is None:
        raise EvidenceError(GENERIC_MESSAGE + " Other kinds of analysis (for example the chest X-ray placeholder) are not supported.")
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        paths = []
        for problem in exc.errors():
            path = ".".join(str(part) for part in problem["loc"])
            if path and path not in paths:
                paths.append(path)
        shown = ", ".join(paths[:5])
        raise EvidenceError(f"{GENERIC_MESSAGE} Problem fields: {shown}.") from exc
