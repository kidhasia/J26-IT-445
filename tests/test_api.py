import json

import pytest
from fastapi.testclient import TestClient

from lumi.config import CLINICAL_BOUNDARY_NOTICE
from lumi.main import create_app
from lumi.pipelines.mock import MOCK_WARNING
from lumi.schemas import InputType
from lumi.service import AnalysisService
from tests.conftest import AUTH_HEADERS, TEST_MAX_UPLOAD_BYTES, make_jpeg, make_pdf, make_png

URL = "/api/v1/analyze"
ENVELOPE_KEYS = {
    "request_id",
    "input_type",
    "result",
    "confidence",
    "answer",
    "explanation",
    "xai_reference",
    "warnings",
    "clinical_boundary_notice",
    "error",
}


def post(client, input_type="skin_image", file=("lesion.png", make_png(), "image/png"), **fields):
    data = {"input_type": input_type, **fields} if input_type is not None else dict(fields)
    files = {"file": file} if file is not None else None
    return client.post(URL, data=data, files=files)


def assert_error(response, status: int, code: str, field: str | None = None) -> dict:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == ENVELOPE_KEYS
    assert body["error"]["code"] == code
    if field is not None:
        assert body["error"]["field"] == field
    assert body["result"] is None and body["answer"] is None and body["confidence"] is None
    assert body["clinical_boundary_notice"] == CLINICAL_BOUNDARY_NOTICE
    assert body["request_id"]
    return body


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.parametrize(
    "input_type, file",
    [
        ("skin_image", ("lesion.png", make_png(), "image/png")),
        ("chest_xray", ("xray.jpg", make_jpeg(), "image/jpeg")),
        ("lab_report", ("report.pdf", make_pdf(), "application/pdf")),
    ],
)
def test_valid_upload_returns_mock_envelope_without_prediction(client, input_type, file):
    response = post(client, input_type=input_type, file=file, question="  What is this?  ")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == ENVELOPE_KEYS
    assert body["input_type"] == input_type
    assert body["error"] is None
    assert body["result"]["status"] == "not_implemented"
    assert body["confidence"] is None
    assert body["answer"] is None
    assert MOCK_WARNING in body["warnings"]
    assert body["clinical_boundary_notice"] == CLINICAL_BOUNDARY_NOTICE


def test_request_ids_are_unique(client):
    first = post(client).json()["request_id"]
    second = post(client).json()["request_id"]
    assert first != second


def test_valid_metadata_accepted(client):
    response = post(client, metadata=json.dumps({"client_platform": "robot", "locale": "en-LK"}))
    assert response.status_code == 200, response.text


def test_invalid_input_type(client):
    body = assert_error(post(client, input_type="mri_scan"), 422, "invalid_input_type", "input_type")
    assert "skin_image" in body["error"]["message"]


def test_missing_input_type(client):
    assert_error(post(client, input_type=None), 422, "missing_field", "input_type")


def test_missing_file(client):
    assert_error(post(client, file=None), 422, "missing_field", "file")


def test_empty_file(client):
    body = assert_error(post(client, file=("empty.png", b"", "image/png")), 400, "empty_file", "file")
    assert body["input_type"] == "skin_image"


def test_unsupported_file_type(client):
    assert_error(post(client, file=("notes.txt", b"hello", "text/plain")), 415, "unsupported_media_type", "file")


def test_pdf_sent_as_skin_image(client):
    assert_error(post(client, file=("r.pdf", make_pdf(), "application/pdf")), 415, "unsupported_media_type")


def test_mismatched_declared_type(client):
    assert_error(post(client, file=("x.jpg", make_png(), "image/jpeg")), 415, "unsupported_media_type")


def test_corrupt_image(client):
    data = make_png((64, 64))
    assert_error(post(client, file=("bad.png", data[:40], "image/png")), 400, "unreadable_file")


def test_file_too_large(client):
    big = make_png() + b"\x00" * TEST_MAX_UPLOAD_BYTES
    assert_error(post(client, file=("big.png", big, "image/png")), 413, "file_too_large")


def test_question_too_long(client):
    assert_error(post(client, question="a" * 1001), 422, "invalid_field", "question")


def test_question_about_the_unfinished_chest_xray_is_not_answered(client):
    response = client.post("/api/v1/analyze", data={"input_type": "chest_xray", "question": "What does this show?"},
                           files={"file": ("x.png", make_png(), "image/png")})
    body = response.json()
    assert response.status_code == 200 and body["answer"] is None
    assert "QUESTION_NOT_ANSWERED" in " ".join(body["warnings"])


def test_question_about_a_pdf_report_is_not_answered(client):
    response = client.post("/api/v1/analyze", data={"input_type": "lab_report", "question": "What was the sodium value?"},
                           files={"file": ("r.pdf", make_pdf(), "application/pdf")})
    body = response.json()
    assert response.status_code == 200 and body["answer"] is None  # a PDF is not read yet, so there is no evidence


def test_blank_question_is_treated_as_absent(client):
    response = post(client, question="   ")
    assert response.status_code == 200
    assert "QUESTION_NOT_ANSWERED" not in " ".join(response.json()["warnings"])


@pytest.mark.parametrize(
    "metadata",
    [
        "not json",
        json.dumps(["a", "list"]),
        json.dumps({"patient_name": "should be rejected"}),
        json.dumps({"client_platform": "smartwatch"}),
    ],
)
def test_invalid_metadata(client, metadata):
    body = assert_error(post(client, metadata=metadata), 422, "invalid_metadata", "metadata")
    assert "should be rejected" not in json.dumps(body)


def test_unexpected_pipeline_failure_returns_500_envelope(settings):
    class BrokenPipeline:
        name = "broken"

        def run(self, file, question):
            raise RuntimeError("secret internal detail")

    service = AnalysisService({t: BrokenPipeline() for t in InputType})
    client = TestClient(
        create_app(settings=settings, service=service), headers=AUTH_HEADERS, raise_server_exceptions=False
    )
    body = assert_error(post(client), 500, "internal_error")
    assert "secret internal detail" not in json.dumps(body)
