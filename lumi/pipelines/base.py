"""The interface every analysis pipeline (skin, chest X-ray, OCR) must implement."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from lumi.validation import ValidatedFile


@dataclass(frozen=True)
class PipelineOutput:
    result: dict[str, Any] | None
    confidence: float | None = None
    answer: str | None = None
    explanation: str | None = None
    xai_reference: str | None = None
    warnings: list[str] = field(default_factory=list)


class Pipeline(Protocol):
    name: str

    def run(self, file: ValidatedFile, question: str | None) -> PipelineOutput: ...
