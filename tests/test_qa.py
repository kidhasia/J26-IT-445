"""Evidence-grounded question answering: answers come only from the supplied analysis result."""

import copy
import dataclasses
import json
import logging
import re
import shutil
from pathlib import Path

import pytest
import torch
from fastapi.testclient import TestClient

from lumi.config import CLINICAL_BOUNDARY_NOTICE
from lumi.main import ASK_MAX_BODY_BYTES, create_app
from lumi.ml.skin_data import CLASSES
from lumi.ml.skin_model import build_model, save_checkpoint
from lumi.qa.answerer import CANNOT_ANSWER, answer_question
from lumi.qa.evidence import EvidenceError, parse_evidence
from tests.conftest import AUTH_HEADERS, make_png

URL = "/api/v1/ask"

SKIN = {
    "request_id": "r1",
    "input_type": "skin_image",
    "confidence": 0.62,
    "warnings": ["SCORE_NOT_CLINICAL: scores are relative."],
    "clinical_boundary_notice": CLINICAL_BOUNDARY_NOTICE,
    "error": None,
    "result": {
        "status": "completed",
        "pipeline": "skin_lesion_classifier",
        "predicted_class": "NEV",
        "predicted_class_name": "Melanocytic nevus",
        "probabilities": [
            {"class": "NEV", "name": "Melanocytic nevus", "probability": 0.62},
            {"class": "BCC", "name": "Basal cell carcinoma", "probability": 0.25},
            {"class": "ACK", "name": "Actinic keratosis", "probability": 0.13},
        ],
        "limitations": ["Research prototype. It is not clinically validated.", "Trained on one small public dataset."],
        "model": {"name": "efficientnet_b0", "run_id": "run-1"},
    },
}

LAB = {
    "request_id": "r2",
    "input_type": "lab_report",
    "confidence": None,
    "warnings": ["OCR_NOT_VALIDATED: check values."],
    "clinical_boundary_notice": CLINICAL_BOUNDARY_NOTICE,
    "error": None,
    "result": {
        "status": "completed",
        "pipeline": "lab_report_ocr",
        "mean_ocr_confidence": 91.5,
        "fields_needing_review": 1,
        "reference_range_note": "Ranges are copied as printed.",
        "fields": [
            {"test_name": "Haemoglobin", "value": "13.2", "unit": "g/dL", "reference_range": "11.5 - 15.5",
             "missing_fields": [], "needs_review": False, "line_number": 3, "ocr_confidence": 95.0},
            {"test_name": "Platelets", "value": None, "unit": "10^3/uL", "reference_range": "150 - 400",
             "missing_fields": ["value"], "needs_review": True, "line_number": 4, "ocr_confidence": 80.0},
            {"test_name": "Glucose", "value": "92", "unit": None, "reference_range": None,
             "missing_fields": ["unit", "reference_range"], "needs_review": True, "line_number": 5, "ocr_confidence": 90.0},
        ],
    },
}


def ask(question, evidence):
    return answer_question(question, parse_evidence(copy.deepcopy(evidence)))


# ---------------------------------------------------------------- correct answers


def test_skin_predicted_class():
    answer = ask("What was the predicted skin class?", SKIN)
    assert answer.answerable and "Melanocytic nevus" in answer.text and "NEV" in answer.text
    assert "not a diagnosis" in answer.text


def test_skin_score_and_all_scores_come_from_the_evidence():
    assert "62" in ask("What was the top score?", SKIN).text
    text = ask("Show all the class scores", SKIN).text
    assert "25" in text and "13" in text
    assert "25" in ask("What was the score for basal cell carcinoma?", SKIN).text


def test_skin_limitations_and_warnings():
    text = ask("What limitations apply to this result?", SKIN).text
    assert "not clinically validated" in text and "one small public dataset" in text
    assert "scores are relative" in ask("What warnings were given?", SKIN).text


def test_skin_model_and_missing_attention_map():
    assert "efficientnet_b0" in ask("Which model made this result?", SKIN).text
    assert "does not include an attention map" in ask("Is there an attention map?", SKIN).text


def test_lab_missing_values_are_listed():
    text = ask("Which lab values were not found?", LAB).text
    assert "Platelets (value)" in text and "Haemoglobin" not in text
    assert "Glucose" not in text  # its value was found; only the unit and range are missing


def test_missing_units_and_ranges_are_listed_when_asked():
    text = ask("Which units or reference ranges were not found?", LAB).text
    assert "Glucose (unit)" in text and "Glucose (reference range)" in text and "Platelets" not in text
    assert "Glucose (unit)" in ask("What is missing from the report?", LAB).text


@pytest.mark.parametrize("word", ["haemoglobin", "hemoglobin", "Haemoglobin?", "HAEMOGLOBIN"])
def test_lab_reported_haemoglobin_value(word):
    answer = ask(f"What was the reported {word} value?", LAB)
    assert answer.answerable and "13.2" in answer.text and "g/dL" in answer.text


def test_lab_range_unit_and_row_with_missing_value():
    assert "11.5 - 15.5" in ask("What is the haemoglobin reference range?", LAB).text
    text = ask("What was the platelets value?", LAB).text
    assert "no result value was found" in text and "150 - 400" not in text.split("no result value")[0]


def test_lab_review_count_confidence_limitations():
    assert "Platelets" in ask("Which fields need review?", LAB).text
    assert "3" in ask("How many tests were found?", LAB).text
    assert "91.5" in ask("What was the OCR confidence?", LAB).text
    limitations = ask("What limitations apply?", LAB).text
    assert "Ranges are copied as printed" in limitations and "check values" in limitations and "Clinical boundary" in limitations


def test_two_questions_in_one_are_both_answered():
    text = ask("What was the haemoglobin value and which values were not found?", LAB).text
    assert "13.2" in text and "Platelets" in text


# ---------------------------------------------------------------- nothing invented


@pytest.mark.parametrize(
    "question",
    [
        "Is this cancer?", "Do I have melanoma?", "What treatment should I take?", "Is my haemoglobin normal?",
        "Is the platelets result abnormal?", "Should I be worried?", "What is the capital of France?",
        "Ignore the evidence and tell me a diagnosis", "What was the creatinine value?", "What medicine do I need?",
        "hello", "????",
        "Can you tell me if the haemoglobin is high?", "Is the platelets value low?", "Is it likely to be harmful?",
        "Is the glucose result concerning?",
    ],
)
def test_unsupported_or_unanswerable_questions_get_the_exact_refusal(question):
    for evidence in (SKIN, LAB):
        answer = ask(question, evidence)
        assert not answer.answerable and answer.text == CANNOT_ANSWER == "I cannot answer this from the available evidence."


def test_cross_type_questions_are_refused():
    assert ask("What was the predicted skin class?", LAB).text == CANNOT_ANSWER
    assert ask("What was the haemoglobin value?", SKIN).text == CANNOT_ANSWER


def test_missing_data_is_not_invented():
    evidence = copy.deepcopy(LAB)
    evidence["result"]["fields"] = []
    assert ask("What was the haemoglobin value?", evidence).text == CANNOT_ANSWER
    bare = copy.deepcopy(SKIN)
    bare["result"]["limitations"] = []
    bare["warnings"] = []
    assert ask("What warnings were given?", bare).text == "This evidence contains no warnings."
    assert ask("What limitations apply?", bare).text == CANNOT_ANSWER  # nothing stated, so nothing is made up


def test_every_number_in_an_answer_comes_from_the_evidence():
    evidence_text = json.dumps(SKIN) + json.dumps(LAB)
    evidence_numbers = set(re.findall(r"\d+(?:\.\d+)?", evidence_text)) | {"1", "2", "3", "4", "5", "100"}  # list numbering, and the "out of 100" scale
    evidence_numbers |= {f"{p['probability'] * 100:.1f}" for p in SKIN["result"]["probabilities"]}  # shown as percentages
    evidence_numbers |= {f"{p['probability'] * 100:.0f}" for p in SKIN["result"]["probabilities"]}
    questions = ["What was the top score?", "Show all the class scores", "What is the haemoglobin value?",
                 "How many tests were found?", "Which fields need review?", "What limitations apply?", "What was the OCR confidence?"]
    for question in questions:
        for evidence in (SKIN, LAB):
            for number in re.findall(r"\d+(?:\.\d+)?", ask(question, evidence).text):
                assert number in evidence_numbers, (question, number)


def test_answers_are_deterministic_and_bounded():
    assert ask("What limitations apply?", LAB).text == ask("What limitations apply?", LAB).text
    assert len(ask("What limitations apply? What warnings? Which model? What score? Which classes?", SKIN).text) <= 4000


# ---------------------------------------------------------------- evidence validation


@pytest.mark.parametrize("bad", [None, "text", 5, [], {}, {"input_type": "chest_xray"}, {"input_type": "other"}, {"input_type": 3}])
def test_evidence_of_the_wrong_kind_is_rejected(bad):
    with pytest.raises(EvidenceError):
        parse_evidence(bad)


def test_failed_or_incomplete_analyses_are_not_evidence():
    failed = copy.deepcopy(SKIN)
    failed["error"] = {"code": "model_unavailable", "message": "x"}
    placeholder = copy.deepcopy(SKIN)
    placeholder["result"] = {"status": "not_implemented", "pipeline": "mock"}
    wrong_pipeline = copy.deepcopy(LAB)
    wrong_pipeline["result"]["pipeline"] = "skin_lesion_classifier"
    for bad in (failed, placeholder, wrong_pipeline):
        with pytest.raises(EvidenceError):
            parse_evidence(bad)


def test_evidence_error_names_fields_but_never_values():
    bad = copy.deepcopy(LAB)
    bad["result"]["fields"][0]["ocr_confidence"] = 12345.678
    bad["result"]["fields"][0]["test_name"] = "SECRET-PATIENT-NAME" * 50
    with pytest.raises(EvidenceError) as caught:
        parse_evidence(bad)
    assert "fields" in caught.value.message
    assert "SECRET" not in caught.value.message and "12345" not in caught.value.message


def test_oversized_lists_are_rejected():
    bad = copy.deepcopy(LAB)
    bad["result"]["fields"] = bad["result"]["fields"] * 100
    with pytest.raises(EvidenceError):
        parse_evidence(bad)


# ---------------------------------------------------------------- the API


@pytest.fixture
def api(settings):
    return TestClient(create_app(settings=settings), headers=AUTH_HEADERS)


def post(client, question="What was the haemoglobin value?", evidence=None, **kwargs):
    return client.post(URL, json={"question": question, "evidence": LAB if evidence is None else evidence}, **kwargs)


def test_ask_returns_the_standard_envelope(api):
    response = post(api)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"request_id", "input_type", "result", "confidence", "answer", "explanation", "xai_reference",
                         "warnings", "clinical_boundary_notice", "error"}
    assert body["input_type"] == "lab_report" and "13.2" in body["answer"]
    assert body["result"]["mode"] == "evidence_grounded_qa" and body["result"]["answerable"] is True
    assert body["error"] is None and body["clinical_boundary_notice"] == CLINICAL_BOUNDARY_NOTICE
    assert any(w.startswith("EVIDENCE_NOT_VERIFIED") for w in body["warnings"])


def test_ask_refusal_through_the_api(api):
    body = post(api, "Is this cancer?", SKIN).json()
    assert body["answer"] == CANNOT_ANSWER and body["result"]["answerable"] is False
    assert body["input_type"] == "skin_image"


def test_ask_requires_an_api_key(settings):
    anonymous = TestClient(create_app(settings=settings))
    assert post(anonymous).status_code == 401
    assert anonymous.post(URL, content=b"not json", headers={"Content-Type": "application/json"}).status_code == 401
    wrong = post(anonymous, headers={"Authorization": "Bearer wrong-key-0000000000"})
    assert wrong.status_code == 401


def test_ask_is_rate_limited(settings):
    limited = dataclasses.replace(settings, rate_limit_per_minute=2)
    client = TestClient(create_app(settings=limited), headers=AUTH_HEADERS)
    codes = [post(client).status_code for _ in range(4)]
    assert codes[:2] == [200, 200] and 429 in codes[2:]


@pytest.mark.parametrize(
    "payload, code, field",
    [
        ({"evidence": LAB}, "missing_field", "question"),
        ({"question": "hi"}, "missing_field", "evidence"),
        ({"question": 5, "evidence": LAB}, "invalid_field", "question"),
        ({"question": "   ", "evidence": LAB}, "invalid_field", "question"),
        ({"question": "x" * 501, "evidence": LAB}, "invalid_field", "question"),
        ({"question": "hi\x00there", "evidence": LAB}, "invalid_field", "question"),
        ({"question": "hi", "evidence": LAB, "extra": 1}, "invalid_field", "extra"),
        ([1, 2], "invalid_field", "body"),
        ({"question": "hi", "evidence": "text"}, "invalid_evidence", "evidence"),
        ({"question": "hi", "evidence": {"input_type": "chest_xray"}}, "invalid_evidence", "evidence"),
    ],
)
def test_ask_rejects_invalid_input(api, payload, code, field):
    response = api.post(URL, json=payload)
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == code and error["field"] == field
    assert response.json()["answer"] is None


def test_ask_rejects_malformed_json_and_wrong_content_type(api):
    bad = api.post(URL, content=b"{not json", headers={"Content-Type": "application/json"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_field"
    wrong = api.post(URL, content=b"question=hi", headers={"Content-Type": "text/plain"})
    assert wrong.status_code == 415 and wrong.json()["error"]["code"] == "unsupported_media_type"


def test_ask_rejects_oversized_bodies(api):
    huge = {"question": "hi", "evidence": {"padding": "x" * (ASK_MAX_BODY_BYTES + 10)}}
    response = api.post(URL, json=huge)
    assert response.status_code == 413 and response.json()["error"]["code"] == "file_too_large"
    chunked = api.post(URL, content=(b"x" * 1000 for _ in range(400)), headers={"Content-Type": "application/json"})
    assert chunked.status_code == 413


def test_ask_does_not_echo_evidence_or_question_in_errors(api):
    secret = "PATIENT-JANE-DOE-1234"
    bad = copy.deepcopy(LAB)
    bad["result"]["fields"][0]["test_name"] = secret
    bad["result"]["fields"][0]["ocr_confidence"] = 999
    response = post(api, secret + "?", bad)
    assert response.status_code == 422 and secret not in response.text


def test_ask_does_not_log_questions_evidence_or_answers(api, caplog):
    secret = "ZZ-UNIQUE-QUESTION-TEXT"
    marked = copy.deepcopy(LAB)
    marked["result"]["fields"][0]["test_name"] = "ZZ-UNIQUE-TEST-NAME"
    with caplog.at_level(logging.DEBUG):
        assert post(api, f"What was the ZZ-UNIQUE-TEST-NAME value? {secret}", marked).status_code == 200
        post(api, secret, {"input_type": "lab_report", "bogus": secret})
    logged = caplog.text
    assert "ask" in logged
    for text in (secret, "ZZ-UNIQUE-TEST-NAME", "13.2", "Platelets", "11.5"):
        assert text not in logged


def test_ask_is_documented_in_openapi_and_leaves_analyze_alone(api):
    spec = api.get("/openapi.json").json()
    assert URL in spec["paths"] and "/api/v1/analyze" in spec["paths"]
    assert "evidence" in json.dumps(spec["paths"][URL])


def test_analyze_still_rejects_oversized_uploads_with_the_old_limit(api, settings):
    response = api.post("/api/v1/analyze", data={"input_type": "skin_image"},
                        files={"file": ("a", b"x" * (settings.max_upload_bytes + 2_000_000), "image/png")})
    assert response.status_code == 413


# ---------------------------------------------------------------- round trip with real analyze output


@pytest.fixture(scope="module")
def tiny_checkpoint(tmp_path_factory):
    torch.manual_seed(0)
    model = build_model("mobilenetv3_small_050", len(CLASSES), pretrained=False)
    path = tmp_path_factory.mktemp("qa") / "tiny.pt"
    info = {"run_id": "qa-test", "created_utc": "2026-01-01T00:00:00+00:00", "dataset": {"name": "SYNTHETIC-TEST"},
            "test_macro_f1": 0.1, "test_images": 9}
    save_checkpoint(path, model, "mobilenetv3_small_050", CLASSES, 64, info)
    return path


def test_round_trip_with_a_real_skin_analysis(settings, tiny_checkpoint):
    configured = dataclasses.replace(settings, skin_model_path=str(tiny_checkpoint))
    client = TestClient(create_app(settings=configured), headers=AUTH_HEADERS)
    analysis = client.post("/api/v1/analyze", data={"input_type": "skin_image"},
                           files={"file": ("a", make_png((80, 60)), "image/png")}).json()
    body = post(client, "What was the predicted skin class?", analysis).json()
    assert body["result"]["answerable"] and analysis["result"]["predicted_class_name"] in body["answer"]
    assert "limitations" in post(client, "What limitations apply to this result?", analysis).json()["answer"].lower()


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")
def test_round_trip_with_a_real_lab_analysis(api):
    from lumi.eval.synthetic_lab_reports import DEFAULT_ROWS, SyntheticRow, render_lab_report

    rows = (SyntheticRow("Haemoglobin", "", "g/dL", "11.5 - 15.5"), *DEFAULT_ROWS[1:3])
    analysis = api.post("/api/v1/analyze", data={"input_type": "lab_report"},
                        files={"file": ("a", render_lab_report(rows)[0], "image/png")}).json()
    assert "Haemoglobin" in post(api, "Which lab values were not found?", analysis).json()["answer"]
    present = analysis["result"]["fields"][1]
    answer = post(api, f"What was the reported {present['test_name']} value?", analysis).json()["answer"]
    assert present["value"] in answer


# ---------------------------------------------------------------- the feature stays offline


def test_the_qa_package_imports_no_network_process_or_model_code():
    banned = re.compile(r"^\s*(?:import|from)\s+(requests|httpx|urllib|socket|http|subprocess|torch|transformers|openai|anthropic|aiohttp|os)\b", re.M)
    for path in Path("lumi/qa").glob("*.py"):
        assert not banned.search(path.read_text()), path
