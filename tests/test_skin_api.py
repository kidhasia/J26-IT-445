"""Skin-lesion endpoint: a real model when configured, an honest 503 when not. No fabricated predictions.

The checkpoint used here is a tiny UNTRAINED test model, so these tests check behaviour and plumbing,
not medical accuracy.
"""

import dataclasses
import json
import logging

import pytest
import torch
from fastapi.testclient import TestClient
from PIL import Image

from lumi.config import CLINICAL_BOUNDARY_NOTICE
from lumi.main import create_app
from lumi.ml.skin_data import CLASSES
from lumi.ml.skin_model import build_model, save_checkpoint
from lumi.pipelines.skin.pipeline import LIMITATIONS, SCORE_WARNING
from tests.conftest import AUTH_HEADERS, make_jpeg, make_pdf, make_png

URL = "/api/v1/analyze"
TINY_ARCH = "mobilenetv3_small_050"


@pytest.fixture(scope="module")
def checkpoint_path(tmp_path_factory):
    torch.manual_seed(0)
    model = build_model(TINY_ARCH, len(CLASSES), pretrained=False)
    path = tmp_path_factory.mktemp("ckpt") / "tiny.pt"
    info = {"run_id": "test-run", "created_utc": "2026-01-01T00:00:00+00:00", "dataset": {"name": "SYNTHETIC-TEST"},
            "test_macro_f1": 0.1234, "test_images": 99}
    save_checkpoint(path, model, TINY_ARCH, CLASSES, 64, info)
    return path


@pytest.fixture
def configured_client(settings, checkpoint_path) -> TestClient:
    configured = dataclasses.replace(settings, skin_model_path=str(checkpoint_path))
    return TestClient(create_app(settings=configured), headers=AUTH_HEADERS)


def default_client(settings, **overrides) -> TestClient:
    """An app built the way production builds it: from settings only."""
    return TestClient(create_app(settings=dataclasses.replace(settings, **overrides)), headers=AUTH_HEADERS)


def upload(client, data: bytes | None = None, mime: str = "image/png", **fields):
    payload = make_png((80, 60)) if data is None else data  # note: b"" must stay an empty file
    return client.post(URL, data={"input_type": "skin_image", **fields}, files={"file": ("lesion", payload, mime)})


# ---------------------------------------------------------------- no model: honest refusal


def test_no_model_configured_returns_503_and_no_prediction(settings):
    response = upload(default_client(settings))
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "model_unavailable"
    assert "not set up" in body["error"]["message"]
    assert body["input_type"] == "skin_image" and body["request_id"]
    assert body["result"] is None and body["confidence"] is None and body["answer"] is None
    assert body["clinical_boundary_notice"] == CLINICAL_BOUNDARY_NOTICE


def test_missing_checkpoint_file_returns_503_without_leaking_the_path(settings, caplog):
    secret_path = "/some/private/folder/missing_model.pt"
    with caplog.at_level(logging.INFO, logger="lumi"):
        client = default_client(settings, skin_model_path=secret_path)  # must not crash at start-up
        response = upload(client)
    assert response.status_code == 503 and response.json()["error"]["code"] == "model_unavailable"
    assert "private" not in response.text and "private" not in caplog.text
    assert '"event": "skin_model_load_failed"' in caplog.text


def test_corrupt_checkpoint_returns_503(settings, tmp_path):
    broken = tmp_path / "broken.pt"
    broken.write_bytes(b"not a checkpoint")
    assert upload(default_client(settings, skin_model_path=str(broken))).status_code == 503


def test_other_input_types_are_unaffected_by_a_missing_skin_model(settings):
    client = default_client(settings)
    response = client.post(URL, data={"input_type": "chest_xray"}, files={"file": ("x.png", make_png(), "image/png")})
    assert response.status_code == 200 and response.json()["result"]["status"] == "not_implemented"


# ---------------------------------------------------------------- real inference


def test_configured_model_returns_a_real_prediction_envelope(configured_client):
    response = upload(configured_client)
    assert response.status_code == 200, response.text
    body = response.json()
    result = body["result"]
    assert result["status"] == "completed" and result["pipeline"] == "skin_lesion_classifier"
    assert result["predicted_class"] in CLASSES
    probabilities = result["probabilities"]
    assert [p["class"] for p in probabilities].count(result["predicted_class"]) == 1 and len(probabilities) == len(CLASSES)
    assert abs(sum(p["probability"] for p in probabilities) - 1.0) < 0.001
    values = [p["probability"] for p in probabilities]
    assert values == sorted(values, reverse=True)
    assert probabilities[0]["class"] == result["predicted_class"]
    assert body["confidence"] == probabilities[0]["probability"]
    assert body["answer"] is None and body["error"] is None
    assert body["clinical_boundary_notice"] == CLINICAL_BOUNDARY_NOTICE


def test_response_states_model_identity_evaluation_and_limitations(configured_client):
    result = upload(configured_client).json()["result"]
    model = result["model"]
    assert model["name"] == TINY_ARCH and model["run_id"] == "test-run" and model["classes"] == list(CLASSES)
    assert model["evaluation"]["held_out_test_macro_f1"] == 0.1234 and model["evaluation"]["held_out_test_images"] == 99
    assert "not a clinical validation" in model["evaluation"]["note"]
    assert result["limitations"] == LIMITATIONS and len(LIMITATIONS) >= 4
    assert "does not provide a diagnosis" in LIMITATIONS[0]
    assert any("under 18" in text for text in LIMITATIONS)  # the pediatric data gap is stated, not hidden
    assert result["input"] == {"width": 80, "height": 60}


def test_confidence_is_labelled_as_not_clinical_certainty(configured_client):
    body = upload(configured_client).json()
    assert SCORE_WARNING in body["warnings"]
    assert "not a diagnosis" in body["explanation"].lower()


def test_same_image_gives_the_same_answer_twice(configured_client):
    first = upload(configured_client).json()["result"]["probabilities"]
    assert upload(configured_client).json()["result"]["probabilities"] == first


def test_question_is_not_answered_yet(configured_client):
    body = upload(configured_client, question="Is this cancer?").json()
    assert body["answer"] is None
    assert any(w.startswith("QUESTION_NOT_ANSWERED") for w in body["warnings"])


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "L"])
@pytest.mark.parametrize("size", [(64, 64), (200, 40), (40, 200), (1, 1)])
def test_unusual_images_are_handled(configured_client, mode, size):
    from io import BytesIO

    buffer = BytesIO()
    Image.new(mode, size, 128 if mode == "L" else (120, 90, 60, 255)[: len(mode)]).save(buffer, format="PNG")
    response = upload(configured_client, buffer.getvalue())
    assert response.status_code == 200, response.text
    assert response.json()["result"]["predicted_class"] in CLASSES


def test_jpeg_upload_works(configured_client):
    assert upload(configured_client, make_jpeg((70, 50)), "image/jpeg").status_code == 200


# ---------------------------------------------------------------- validation, security and privacy still apply


def test_invalid_uploads_are_rejected_before_the_model_runs(configured_client):
    assert upload(configured_client, b"", "image/png").status_code == 400
    assert upload(configured_client, make_png()[:30], "image/png").status_code == 400
    assert upload(configured_client, make_pdf(), "application/pdf").status_code == 415


def test_skin_endpoint_still_requires_an_api_key(settings, checkpoint_path):
    configured = dataclasses.replace(settings, skin_model_path=str(checkpoint_path))
    anonymous = TestClient(create_app(settings=configured))
    assert upload(anonymous).status_code == 401


def test_predictions_and_probabilities_are_not_written_to_logs(configured_client, caplog):
    with caplog.at_level(logging.DEBUG):
        body = upload(configured_client, question="private question text").json()
    assert body["result"]["predicted_class"]
    for forbidden in ["predicted_class", "probabilit", "private question text", "lesion"]:
        assert forbidden not in caplog.text
    assert '"input_type": "skin_image"' in caplog.text  # the normal request log line is still there


def test_response_is_valid_json_with_the_standard_envelope_keys(configured_client):
    body = json.loads(upload(configured_client).text)
    assert set(body) == {"request_id", "input_type", "result", "confidence", "answer", "explanation", "xai_reference",
                         "warnings", "clinical_boundary_notice", "error"}
