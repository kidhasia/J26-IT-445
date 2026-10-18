"""The attention-map feature through the real API (with auth, validation and logging in place).

Checkpoints are small UNTRAINED models, so these tests check behaviour and correctness of the plumbing, not medical
meaning."""

import base64
import dataclasses
import io
import json
import logging

import numpy as np
import pytest
import torch
from fastapi.testclient import TestClient
from PIL import Image

from lumi.config import CLINICAL_BOUNDARY_NOTICE
from lumi.main import create_app
from lumi.ml import gradcam
from lumi.ml.skin_data import CLASSES
from lumi.ml.skin_model import build_model, save_checkpoint
from lumi.pipelines import skin as skin_package  # noqa: F401  (ensures the package imports)
from lumi.pipelines.skin import pipeline as skin_pipeline
from tests.conftest import AUTH_HEADERS, make_pdf, make_png

URL = "/api/v1/analyze"
LABEL = "AI attention visualisation — not a diagnosis or proof of correctness."


def make_checkpoint(directory, arch: str, positive_head: bool = False):
    torch.manual_seed(0)
    model = build_model(arch, len(CLASSES), pretrained=False)
    if positive_head:
        model.classifier.weight.data.abs_()
    path = directory / f"{arch}.pt"
    save_checkpoint(path, model, arch, CLASSES, 64, {"run_id": f"test-{arch}", "test_macro_f1": 0.5, "test_images": 10})
    return path


@pytest.fixture(scope="module")
def checkpoints(tmp_path_factory):
    folder = tmp_path_factory.mktemp("explain_ckpts")
    return {
        "tiny": make_checkpoint(folder, "mobilenetv3_small_050"),  # explained through the generic blocks[-1] layer
        "effnet": make_checkpoint(folder, "efficientnet_b0", positive_head=True),  # the real architecture, layer bn2
        "resnet": make_checkpoint(folder, "resnet18"),  # no Grad-CAM layer defined for it
    }


def client_for(settings, checkpoint) -> TestClient:
    configured = dataclasses.replace(settings, skin_model_path=str(checkpoint))
    return TestClient(create_app(settings=configured), headers=AUTH_HEADERS)


@pytest.fixture
def tiny_client(settings, checkpoints):
    return client_for(settings, checkpoints["tiny"])


def png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def upload(client, data: bytes | None = None, input_type: str = "skin_image", mime: str = "image/png", **fields):
    payload = make_png((80, 60)) if data is None else data
    return client.post(URL, data={"input_type": input_type, **fields}, files={"file": ("photo", payload, mime)})


def decode_overlay(body) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(body["result"]["explanation_image"]["image_base64"])))


def warning_codes(body) -> list[str]:
    return [w.split(":")[0] for w in body["warnings"]]


# ---------------------------------------------------------------- the feature works


def test_explain_true_returns_an_attention_map_for_the_predicted_class(tiny_client):
    body = upload(tiny_client, explain="true").json()
    result, image = body["result"], body["result"]["explanation_image"]
    assert body["error"] is None and result["status"] == "completed"
    assert image["kind"] == "grad_cam_overlay" and image["method"] == "Grad-CAM"
    assert image["target_class"] == result["predicted_class"]
    assert image["target_layer"] == "blocks[-1]" and len(image["map_cells"]) == 2
    assert image["label"] == LABEL
    assert image["mime_type"] == "image/jpeg" and len(image["limitations"]) >= 3 and image["how_to_read"]
    assert body["xai_reference"] == f"grad_cam:blocks[-1]:{result['predicted_class']}"
    assert "attention map" in body["explanation"] and "not a diagnosis" in body["explanation"]
    assert body["clinical_boundary_notice"] == CLINICAL_BOUNDARY_NOTICE


def test_overlay_is_a_real_jpeg_with_the_uploaded_images_shape(tiny_client):
    body = upload(tiny_client, png_bytes(Image.new("RGB", (120, 40), (90, 60, 30))), explain="true").json()
    overlay = decode_overlay(body)
    assert overlay.format == "JPEG" and overlay.size == (120, 40)
    assert (body["result"]["explanation_image"]["width"], body["result"]["explanation_image"]["height"]) == (120, 40)


def test_the_real_efficientnet_architecture_is_explained_through_bn2(settings, checkpoints):
    body = upload(client_for(settings, checkpoints["effnet"]), explain="true").json()
    image = body["result"]["explanation_image"]
    assert image["target_layer"] == "bn2" and image["map_cells"] == [2, 2]  # 64 px input -> 2 x 2 map
    assert body["xai_reference"].startswith("grad_cam:bn2:")


def test_explain_is_off_by_default_and_changes_nothing_else(tiny_client):
    plain = upload(tiny_client).json()
    explicit_off = upload(tiny_client, explain="false").json()
    explained = upload(tiny_client, explain="true").json()
    for body in (plain, explicit_off):
        assert "explanation_image" not in body["result"] and body["xai_reference"] is None
        assert "No attention map was produced" in body["explanation"]
    # the same prediction either way: the map comes from the same model and image
    assert explained["confidence"] == plain["confidence"]
    assert explained["result"]["probabilities"] == plain["result"]["probabilities"]
    assert explained["result"]["predicted_class"] == plain["result"]["predicted_class"]


def test_the_map_is_generated_from_the_uploaded_image_not_a_fixed_picture(tiny_client):
    horizontal = Image.fromarray(np.tile(np.linspace(0, 255, 96, dtype=np.uint8), (96, 1)), mode="L").convert("RGB")
    vertical = Image.fromarray(np.tile(np.linspace(0, 255, 96, dtype=np.uint8)[:, None], (1, 96)), mode="L").convert("RGB")
    overlay_h = decode_overlay(upload(tiny_client, png_bytes(horizontal), explain="true").json())
    overlay_v = decode_overlay(upload(tiny_client, png_bytes(vertical), explain="true").json())
    assert overlay_h.tobytes() != overlay_v.tobytes()

    def luminance(image):
        return np.asarray(image.convert("L"), dtype=np.float32).ravel()

    def correlation(a, b):
        return float(np.corrcoef(luminance(a), luminance(b))[0, 1])

    # each overlay still shows its OWN photo underneath (the colour is blended on top of it)
    assert correlation(overlay_h, horizontal) > 0.5 > abs(correlation(overlay_h, vertical))
    assert correlation(overlay_v, vertical) > 0.5 > abs(correlation(overlay_v, horizontal))


def test_response_stays_small_for_big_photos(settings, checkpoints):
    roomy = dataclasses.replace(settings, max_upload_bytes=5_000_000, max_image_pixels=10_000_000)  # the fixture limits are tiny
    client = client_for(roomy, checkpoints["tiny"])
    photo = Image.new("RGB", (1600, 1200), (120, 80, 60))
    response = upload(client, png_bytes(photo), explain="true")
    assert response.status_code == 200
    overlay = decode_overlay(response.json())
    assert max(overlay.size) == 512 and overlay.size == (512, 384)
    assert len(response.content) < 300_000


# ---------------------------------------------------------------- honest behaviour when no map is possible


def test_unsupported_architecture_still_returns_the_prediction_with_a_warning(settings, checkpoints):
    body = upload(client_for(settings, checkpoints["resnet"]), explain="true").json()
    assert body["result"]["status"] == "completed" and body["result"]["predicted_class"] in CLASSES
    assert "explanation_image" not in body["result"] and body["xai_reference"] is None
    assert "EXPLANATION_UNSUPPORTED" in warning_codes(body)


def test_empty_map_is_not_invented(tiny_client, monkeypatch):
    def empty(*args, **kwargs):
        raise gradcam.ExplanationEmpty("nothing positive")

    monkeypatch.setattr(skin_pipeline.gradcam, "compute_grad_cam", empty)
    body = upload(tiny_client, explain="true").json()
    assert body["result"]["predicted_class"] in CLASSES and "explanation_image" not in body["result"]
    assert "EXPLANATION_EMPTY" in warning_codes(body)


@pytest.mark.parametrize("error", [gradcam.ExplanationError("x"), RuntimeError("secret internal detail"), MemoryError()])
def test_any_explanation_failure_keeps_the_prediction(tiny_client, monkeypatch, error, caplog):
    def broken(*args, **kwargs):
        raise error

    monkeypatch.setattr(skin_pipeline.gradcam, "compute_grad_cam", broken)
    with caplog.at_level(logging.INFO, logger="lumi"):
        response = upload(tiny_client, explain="true")
    body = response.json()
    assert response.status_code == 200 and body["result"]["predicted_class"] in CLASSES
    assert "EXPLANATION_FAILED" in warning_codes(body) and "explanation_image" not in body["result"]
    assert "secret internal detail" not in response.text and "secret internal detail" not in caplog.text


def test_a_drawing_failure_keeps_the_prediction(tiny_client, monkeypatch):
    def broken(*args, **kwargs):
        raise ValueError("cannot draw")

    monkeypatch.setattr(skin_pipeline.gradcam, "make_overlay", broken)
    body = upload(tiny_client, explain="true").json()
    assert body["result"]["predicted_class"] in CLASSES and "EXPLANATION_FAILED" in warning_codes(body)
    assert "explanation_image" not in body["result"] and body["xai_reference"] is None


@pytest.mark.parametrize("input_type", ["lab_report", "chest_xray"])
def test_other_input_types_say_that_no_map_exists(tiny_client, input_type):
    response = upload(tiny_client, input_type=input_type, explain="true")
    body = response.json()
    assert response.status_code == 200 and "EXPLANATION_NOT_AVAILABLE" in warning_codes(body)
    assert "explanation_image" not in (body["result"] or {}) and body["xai_reference"] is None


# ---------------------------------------------------------------- errors, security and privacy still hold


def test_no_model_configured_still_gives_503_even_when_a_map_is_requested(settings):
    client = TestClient(create_app(settings=settings), headers=AUTH_HEADERS)
    response = upload(client, explain="true")
    assert response.status_code == 503 and response.json()["error"]["code"] == "model_unavailable"
    assert response.json()["result"] is None


def test_invalid_explain_value_is_a_clear_422(tiny_client):
    response = upload(tiny_client, explain="banana")
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_field" and error["field"] == "explain"


@pytest.mark.parametrize("value, expected", [("true", True), ("1", True), ("false", False), ("0", False)])
def test_common_true_and_false_spellings_are_accepted(tiny_client, value, expected):
    assert ("explanation_image" in upload(tiny_client, explain=value).json()["result"]) is expected


def test_bad_uploads_are_rejected_before_any_map_is_attempted(tiny_client):
    assert upload(tiny_client, b"", explain="true").status_code == 400
    assert upload(tiny_client, make_png()[:30], explain="true").status_code == 400
    assert upload(tiny_client, make_pdf(), mime="application/pdf", explain="true").status_code == 415


def test_a_map_still_requires_an_api_key(settings, checkpoints):
    configured = dataclasses.replace(settings, skin_model_path=str(checkpoints["tiny"]))
    assert upload(TestClient(create_app(settings=configured)), explain="true").status_code == 401


def test_images_and_maps_never_reach_the_logs(tiny_client, caplog):
    with caplog.at_level(logging.DEBUG):
        body = upload(tiny_client, explain="true", question="private question text").json()
    payload = body["result"]["explanation_image"]["image_base64"]
    assert payload[:40] not in caplog.text
    for forbidden in ["image_base64", "grad_cam", "predicted_class", "private question text"]:
        assert forbidden not in caplog.text
    logged = [json.loads(line[line.index("{") :]) for line in caplog.text.splitlines() if '"event": "analyze"' in line]
    assert logged and logged[-1]["explain_requested"] is True


def test_response_keeps_the_standard_envelope(tiny_client):
    body = upload(tiny_client, explain="true").json()
    assert set(body) == {"request_id", "input_type", "result", "confidence", "answer", "explanation", "xai_reference",
                         "warnings", "clinical_boundary_notice", "error"}
