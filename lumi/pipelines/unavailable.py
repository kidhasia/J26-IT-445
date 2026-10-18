"""Pipeline used when a model is not set up on this server. It never produces a prediction."""

from lumi.errors import LumiError
from lumi.pipelines.base import PipelineOutput
from lumi.schemas import ErrorCode
from lumi.validation import ValidatedFile


class ModelUnavailablePipeline:
    status = "unavailable"

    def __init__(self, name: str, message: str):
        self.name = name
        self._message = message

    def run(self, file: ValidatedFile, question: str | None) -> PipelineOutput:
        raise LumiError(503, ErrorCode.MODEL_UNAVAILABLE, self._message)
