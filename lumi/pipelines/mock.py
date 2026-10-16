"""Explicit placeholder pipeline used until real models exist.

It never produces a prediction, label, confidence or answer. It only reports that the file
was received and that no analysis was performed.
"""

from lumi.pipelines.base import PipelineOutput
from lumi.schemas import InputType
from lumi.validation import ValidatedFile

MOCK_WARNING = "MOCK_PIPELINE: no model was run. This response contains no medical finding."
UNANSWERED_QUESTION_WARNING = "QUESTION_NOT_ANSWERED: the reasoning layer is not implemented yet."


class MockPipeline:
    def __init__(self, input_type: InputType):
        self.input_type = input_type
        self.name = f"mock_{input_type.value}"

    def run(self, file: ValidatedFile, question: str | None) -> PipelineOutput:
        warnings = [MOCK_WARNING]
        if question is not None:
            warnings.append(UNANSWERED_QUESTION_WARNING)
        return PipelineOutput(
            result={
                "status": "not_implemented",
                "pipeline": self.name,
                "received_mime_type": file.mime_type,
                "received_bytes": len(file.data),
            },
            explanation=f"No analysis was performed: the {self.input_type.value} pipeline is not implemented yet.",
            warnings=warnings,
        )
