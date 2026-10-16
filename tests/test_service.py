import pytest

from lumi.config import CLINICAL_BOUNDARY_NOTICE
from lumi.pipelines.base import PipelineOutput
from lumi.pipelines.mock import MOCK_WARNING, UNANSWERED_QUESTION_WARNING, MockPipeline
from lumi.schemas import InputType
from lumi.service import AnalysisService, build_default_service
from lumi.validation import ValidatedFile
from tests.conftest import make_png

FILE = ValidatedFile(data=make_png(), mime_type="image/png", filename="x.png")


class RecordingPipeline:
    def __init__(self, name: str):
        self.name = name
        self.calls = 0

    def run(self, file, question):
        self.calls += 1
        return PipelineOutput(result={"pipeline": self.name})


@pytest.mark.parametrize("input_type", list(InputType))
def test_router_sends_each_input_type_to_its_own_pipeline(input_type):
    pipelines = {t: RecordingPipeline(t.value) for t in InputType}
    service = AnalysisService(pipelines)
    response = service.analyze("req1", input_type, FILE, None, None)
    assert response.result == {"pipeline": input_type.value}
    assert pipelines[input_type].calls == 1
    assert sum(p.calls for p in pipelines.values()) == 1


def test_service_requires_a_pipeline_for_every_input_type():
    with pytest.raises(ValueError):
        AnalysisService({InputType.SKIN_IMAGE: RecordingPipeline("skin")})


def test_mock_pipeline_makes_no_prediction():
    output = MockPipeline(InputType.SKIN_IMAGE).run(FILE, None)
    assert output.confidence is None
    assert output.answer is None
    assert output.xai_reference is None
    assert output.result["status"] == "not_implemented"
    assert MOCK_WARNING in output.warnings


def test_mock_pipeline_flags_unanswered_question():
    output = MockPipeline(InputType.LAB_REPORT).run(FILE, "What does my haemoglobin mean?")
    assert output.answer is None
    assert UNANSWERED_QUESTION_WARNING in output.warnings


def test_default_service_response_carries_boundary_notice_and_request_id():
    response = build_default_service().analyze("req42", InputType.CHEST_XRAY, FILE, None, None)
    assert response.request_id == "req42"
    assert response.input_type == InputType.CHEST_XRAY
    assert response.clinical_boundary_notice == CLINICAL_BOUNDARY_NOTICE
    assert response.error is None
