"""Shared request/response models. Every endpoint response uses AnalyzeResponse."""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class InputType(str, Enum):
    SKIN_IMAGE = "skin_image"
    CHEST_XRAY = "chest_xray"
    LAB_REPORT = "lab_report"


class ErrorCode(str, Enum):
    MISSING_FIELD = "missing_field"
    INVALID_INPUT_TYPE = "invalid_input_type"
    INVALID_FIELD = "invalid_field"
    INVALID_METADATA = "invalid_metadata"
    EMPTY_FILE = "empty_file"
    FILE_TOO_LARGE = "file_too_large"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    UNREADABLE_FILE = "unreadable_file"
    UNAUTHORIZED = "unauthorized"
    RATE_LIMITED = "rate_limited"
    INTERNAL_ERROR = "internal_error"


class ErrorDetail(BaseModel):
    code: ErrorCode
    message: str
    field: str | None = None


class RequestMetadata(BaseModel):
    """Optional, non-sensitive client metadata.

    Only these keys are allowed; anything else (names, IDs, dates of birth...) is rejected,
    so patient identifiers cannot slip in through this field.
    """

    model_config = ConfigDict(extra="forbid")

    client_platform: Literal["web", "mobile", "robot", "test"] | None = None
    client_version: str | None = Field(default=None, max_length=32)
    locale: str | None = Field(default=None, max_length=16)


class AnalyzeResponse(BaseModel):
    request_id: str
    input_type: InputType | None
    result: dict[str, Any] | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    answer: str | None = None
    explanation: str | None = None
    xai_reference: str | None = None
    warnings: list[str] = Field(default_factory=list)
    clinical_boundary_notice: str
    error: ErrorDetail | None = None
