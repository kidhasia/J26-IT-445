"""OCR through the real API: auth, validation and envelope rules from M1/M2 still apply."""

import json
import logging
import shutil

import pytest
from fastapi.testclient import TestClient

from lumi.config import CLINICAL_BOUNDARY_NOTICE
from lumi.eval.synthetic_lab_reports import DEFAULT_ROWS, SyntheticRow, render_blank_image, render_lab_report
from lumi.main import create_app
from lumi.pipelines.mock import MOCK_WARNING, UNANSWERED_QUESTION_WARNING, MockPipeline
from lumi.pipelines.ocr.engine import OcrLine, OcrResult, OcrUnavailableError
from lumi.pipelines.ocr.pipeline import PDF_NOT_SUPPORTED_WARNING, REFERENCE_RANGE_NOTE, LabReportOcrPipeline
from lumi.schemas import InputType
from lumi.service import AnalysisService
from tests.conftest import AUTH_HEADERS, make_pdf, make_png

URL = "/api/v1/analyze"
requires_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")


def upload(client, image: bytes, mime: str = "image/png", **fields):
    return client.post(URL, data={"input_type": "lab_report", **fields}, files={"file": ("report", image, mime)})


def warning_codes(body) -> list[str]:
    return [warning.split(":")[0] for warning in body["warnings"]]


class FakeEngine:
    """Returns fixed OCR lines, or raises, so API behaviour can be tested without Tesseract."""

    def __init__(self, lines=None, error: Exception | None = None):
        self.lines = lines or []
        self.error = error

    def extract(self, image_bytes):
        if self.error:
            raise self.error
        return OcrResult(lines=self.lines, engine_name="fake", engine_version="0", language="eng")


def client_with_engine(settings, engine) -> TestClient:
    service = AnalysisService(
        {
            InputType.SKIN_IMAGE: MockPipeline(InputType.SKIN_IMAGE),
            InputType.CHEST_XRAY: MockPipeline(InputType.CHEST_XRAY),
            InputType.LAB_REPORT: LabReportOcrPipeline(engine),
        }
    )
    return TestClient(create_app(settings=settings, service=service), headers=AUTH_HEADERS)


# ---- real Tesseract on synthetic reports ----


@requires_tesseract
@pytest.mark.parametrize("image_format, mime", [("PNG", "image/png"), ("JPEG", "image/jpeg")])
def test_synthetic_report_fields_match_ground_truth(client, image_format, mime):
    image, truth = render_lab_report(image_format=image_format)
    response = upload(client, image, mime)
    assert response.status_code == 200, response.text
    body = response.json()
    result = body["result"]
    assert result["status"] == "completed"
    assert "Haemoglobin" in result["extracted_text"]
    parsed = {f["test_name"]: (f["value"], f["unit"], f["reference_range"]) for f in result["fields"]}
    expected = {r["test_name"]: (r["value"], r["unit"], r["reference_range"]) for r in truth["rows"]}
    assert parsed == expected
    assert body["confidence"] is None and body["answer"] is None
    assert result["reference_range_note"] == REFERENCE_RANGE_NOTE
    assert "OCR_NOT_VALIDATED" in warning_codes(body)
    assert body["clinical_boundary_notice"] == CLINICAL_BOUNDARY_NOTICE


@requires_tesseract
def test_missing_value_in_report_is_flagged_not_guessed(client):
    rows = (SyntheticRow("Haemoglobin", "", "g/dL", "11.5 - 15.5"), *DEFAULT_ROWS[1:3])
    body = upload(client, render_lab_report(rows)[0]).json()
    haemoglobin = next(f for f in body["result"]["fields"] if f["test_name"] == "Haemoglobin")
    assert haemoglobin["value"] is None
    assert "value" in haemoglobin["missing_fields"]
    assert haemoglobin["needs_review"] is True
    assert "FIELDS_NEED_REVIEW" in warning_codes(body)


@requires_tesseract
def test_blank_image_reports_no_text(client):
    body = upload(client, render_blank_image()).json()
    assert body["result"]["fields"] == []
    assert body["result"]["extracted_text"] == ""
    assert "NO_TEXT_FOUND" in warning_codes(body)


# ---- deterministic behaviour with a fake engine ----


def test_text_without_result_rows_reports_no_fields(settings):
    client = client_with_engine(settings, FakeEngine([OcrLine("Some unrelated letter text", 90.0)]))
    body = upload(client, make_png()).json()
    assert body["result"]["fields"] == []
    assert "NO_FIELDS_PARSED" in warning_codes(body)


def test_question_sent_with_the_report_is_answered_from_that_reports_result(settings):
    client = client_with_engine(settings, FakeEngine([OcrLine("Sodium 139 mmol/L 135 - 145", 90.0)]))
    body = upload(client, make_png(), question="What was the reported sodium value?").json()
    assert "139" in body["answer"] and "mmol/L" in body["answer"]
    assert UNANSWERED_QUESTION_WARNING not in body["warnings"]


def test_judging_question_sent_with_the_report_gets_the_refusal(settings):
    client = client_with_engine(settings, FakeEngine([OcrLine("Sodium 139 mmol/L 135 - 145", 90.0)]))
    body = upload(client, make_png(), question="Is this normal?").json()
    assert body["answer"] == "I cannot answer this from the available evidence."
    assert body["result"]["fields"][0]["value"] == "139"


def test_question_about_a_report_with_no_rows_is_refused_not_guessed(settings):
    client = client_with_engine(settings, FakeEngine([OcrLine("Some unrelated letter text", 90.0)]))
    body = upload(client, make_png(), question="What was the sodium value?").json()
    assert body["answer"] == "I cannot answer this from the available evidence."


def test_question_and_report_text_are_not_logged(settings, caplog):
    client = client_with_engine(settings, FakeEngine([OcrLine("Sodium 139 mmol/L 135 - 145", 90.0)]))
    with caplog.at_level("DEBUG"):
        upload(client, make_png(), question="What was the ZZUNIQUEQUESTION sodium value?")
    assert "ZZUNIQUEQUESTION" not in caplog.text and "139" not in caplog.text and "Sodium" not in caplog.text


def test_ocr_unavailable_returns_503_envelope(settings):
    client = client_with_engine(settings, FakeEngine(error=OcrUnavailableError("not installed")))
    response = upload(client, make_png())
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "ocr_unavailable"
    assert body["input_type"] == "lab_report"
    assert body["request_id"]
    assert body["result"] is None


def test_pdf_still_uses_explicit_mock(client):
    body = upload(client, make_pdf(), "application/pdf").json()
    assert body["result"]["status"] == "not_implemented"
    assert MOCK_WARNING in body["warnings"]
    assert PDF_NOT_SUPPORTED_WARNING in body["warnings"]


# ---- existing validation and security still apply to lab reports ----


def test_corrupt_report_image_rejected(client):
    image, _ = render_lab_report()
    response = upload(client, image[:200])
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unreadable_file"


@pytest.mark.parametrize(
    "filename_bytes_mime",
    [(b"GIF89a....", "image/gif"), (b"Haemoglobin 12.1", "text/plain"), (b"<html></html>", "text/html")],
)
def test_unsupported_report_format_rejected(client, filename_bytes_mime):
    data, mime = filename_bytes_mime
    response = upload(client, data, mime)
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_missing_file_for_lab_report(client):
    response = client.post(URL, data={"input_type": "lab_report"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "missing_field"


def test_wrong_field_name_for_file_is_malformed(client):
    response = client.post(URL, data={"input_type": "lab_report"}, files={"report": ("r.png", make_png(), "image/png")})
    assert response.status_code == 422
    assert response.json()["error"]["field"] == "file"


def test_lab_report_requires_auth(anonymous_client):
    response = upload(anonymous_client, make_png())
    assert response.status_code == 401


# ---- privacy ----


def test_report_contents_never_reach_logs(settings, caplog):
    lines = [OcrLine("Report ID: SYN-7777", 90.0), OcrLine("Haemoglobin 12.1 g/dL 11.5 - 15.5", 90.0)]
    client = client_with_engine(settings, FakeEngine(lines))
    with caplog.at_level(logging.DEBUG):
        response = upload(client, make_png(), question="What is my haemoglobin?")
    assert response.status_code == 200
    assert "Haemoglobin" in json.dumps(response.json())  # the client does get the text back...
    for secret in ["Haemoglobin", "haemoglobin", "SYN-7777", "12.1", "11.5"]:
        assert secret not in caplog.text  # ...but the logs never contain it
