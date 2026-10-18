"""Grad-CAM engine tests. Models are randomly initialised (no training data involved); they check the maths and the
safety behaviour, not medical meaning."""

import base64
import io

import numpy as np
import pytest
import torch
from PIL import Image

from lumi.ml import gradcam
from lumi.ml.gradcam import (
    ExplanationEmpty,
    ExplanationError,
    ExplanationUnsupported,
    compute_grad_cam,
    encode_jpeg_base64,
    find_target_layer,
    jet_colors,
    make_overlay,
)
from lumi.ml.skin_model import FILL_RGB, build_model, letterbox, letterbox_geometry

SIZE = 128


@pytest.fixture(scope="module")
def model():
    """EfficientNet-B0 with the same structure as the real model. Classifier weights are made positive so the
    attention map is never empty by accident."""
    torch.manual_seed(0)
    net = build_model("efficientnet_b0", 6, pretrained=False)
    net.classifier.weight.data.abs_()
    return net.eval()


@pytest.fixture
def x():
    torch.manual_seed(1)
    return torch.randn(1, 3, SIZE, SIZE)


# ---------------------------------------------------------------- the maths


def test_grad_cam_equals_the_classic_class_activation_map(model, x):
    """The head is average-pool + one linear layer, so Grad-CAM must equal CAM = ReLU(sum_k W[c,k] * A_k).
    This compares the implementation against that independent formula."""
    name, layer = find_target_layer(model, "efficientnet_b0")
    result = compute_grad_cam(model, x, layer, name, class_index=2)

    captured = {}
    handle = layer.register_forward_hook(lambda m, i, o: captured.__setitem__("a", o.detach()))
    with torch.no_grad():
        model(x)
    handle.remove()
    weights = model.classifier.weight[2].detach()
    reference = torch.relu(torch.einsum("k,bkhw->bhw", weights, captured["a"]))[None]
    reference = torch.nn.functional.interpolate(reference, size=(SIZE, SIZE), mode="bilinear", align_corners=False)[0, 0].numpy()
    reference = reference / reference.max()

    assert name == "bn2"
    assert np.allclose(result.cam, reference, atol=1e-4)


def test_map_shape_range_and_scaling(model, x):
    name, layer = find_target_layer(model, "efficientnet_b0")
    cam = compute_grad_cam(model, x, layer, name).cam
    assert cam.shape == (SIZE, SIZE) and cam.dtype == np.float32
    assert np.isfinite(cam).all() and cam.min() >= 0.0 and cam.max() == pytest.approx(1.0)


def test_probabilities_come_from_the_same_forward_pass_and_default_to_the_top_class(model, x):
    name, layer = find_target_layer(model, "efficientnet_b0")
    result = compute_grad_cam(model, x, layer, name)
    with torch.no_grad():
        expected = torch.softmax(model(x), dim=1)[0].numpy()
    assert np.allclose(result.probabilities, expected, atol=1e-6)
    assert result.class_index == int(expected.argmax())
    assert result.probabilities.sum() == pytest.approx(1.0, abs=1e-5)


def test_different_classes_give_different_maps(model, x):
    name, layer = find_target_layer(model, "efficientnet_b0")
    first = compute_grad_cam(model, x, layer, name, class_index=0).cam
    second = compute_grad_cam(model, x, layer, name, class_index=3).cam
    assert not np.allclose(first, second, atol=1e-3)


def test_different_images_give_different_maps(model):
    name, layer = find_target_layer(model, "efficientnet_b0")
    torch.manual_seed(5)
    a, b = torch.randn(1, 3, SIZE, SIZE), torch.randn(1, 3, SIZE, SIZE)
    assert not np.allclose(compute_grad_cam(model, a, layer, name, 1).cam, compute_grad_cam(model, b, layer, name, 1).cam, atol=1e-3)


def test_same_input_gives_the_same_map(model, x):
    name, layer = find_target_layer(model, "efficientnet_b0")
    assert np.array_equal(compute_grad_cam(model, x, layer, name).cam, compute_grad_cam(model, x, layer, name).cam)


def test_the_input_tensor_is_not_modified(model, x):
    name, layer = find_target_layer(model, "efficientnet_b0")
    before = x.clone()
    compute_grad_cam(model, x, layer, name)
    assert torch.equal(x, before) and not x.requires_grad


# ---------------------------------------------------------------- failure handling


def test_hooks_are_removed_after_success_and_after_failure(model, x):
    name, layer = find_target_layer(model, "efficientnet_b0")
    compute_grad_cam(model, x, layer, name)
    assert len(layer._forward_hooks) == 0
    with pytest.raises(ExplanationError):
        compute_grad_cam(model, x, layer, name, class_index=99)
    assert len(layer._forward_hooks) == 0


def test_invalid_class_index_is_an_explanation_error(model, x):
    name, layer = find_target_layer(model, "efficientnet_b0")
    for bad in (-1, 6, 1000):
        with pytest.raises(ExplanationError):
            compute_grad_cam(model, x, layer, name, class_index=bad)


def test_a_map_with_no_positive_evidence_is_refused_not_invented():
    torch.manual_seed(0)
    net = build_model("efficientnet_b0", 6, pretrained=False).eval()
    net.classifier.weight.data.zero_()  # no class score depends on the image any more
    name, layer = find_target_layer(net, "efficientnet_b0")
    with pytest.raises(ExplanationEmpty):
        compute_grad_cam(net, torch.randn(1, 3, SIZE, SIZE), layer, name)


def test_non_finite_input_is_an_explanation_error(model):
    name, layer = find_target_layer(model, "efficientnet_b0")
    with pytest.raises(ExplanationError):
        compute_grad_cam(model, torch.full((1, 3, SIZE, SIZE), float("nan")), layer, name)


def test_unsupported_architectures_are_reported():
    with pytest.raises(ExplanationUnsupported):
        find_target_layer(torch.nn.Sequential(torch.nn.Linear(2, 2)), "mystery_net")
    resnet = build_model("resnet18", 6, pretrained=False)  # has no `blocks` stage list
    with pytest.raises(ExplanationUnsupported):
        find_target_layer(resnet, "resnet18")


def test_fallback_layer_works_for_other_efficientnet_family_models():
    tiny = build_model("mobilenetv3_small_050", 6, pretrained=False).eval()
    name, layer = find_target_layer(tiny, "mobilenetv3_small_050")
    assert name == "blocks[-1]"
    assert compute_grad_cam(tiny, torch.randn(1, 3, 96, 96), layer, name).cam.shape == (96, 96)


# ---------------------------------------------------------------- geometry and overlay


@pytest.mark.parametrize("image_size", [(300, 300), (400, 100), (100, 400), (1, 1), (257, 255)])
def test_geometry_matches_what_letterbox_actually_does(image_size):
    red = Image.new("RGB", image_size, (255, 0, 0))
    padded = np.asarray(letterbox(red, 64))
    width, height, left, top = letterbox_geometry(image_size, 64)
    is_photo = np.all(padded == np.array([255, 0, 0]), axis=-1)
    rows, cols = np.where(is_photo)
    assert (cols.min(), rows.min()) == (left, top) or (width <= 2 or height <= 2)
    assert abs((cols.max() - cols.min() + 1) - width) <= 1 and abs((rows.max() - rows.min() + 1) - height) <= 1
    assert tuple(padded[0, 0]) in (FILL_RGB, (255, 0, 0))


def hot_spot(size: int, row: slice, col: slice) -> np.ndarray:
    cam = np.zeros((size, size), dtype=np.float32)
    cam[row, col] = 1.0
    return cam


def test_overlay_keeps_the_photo_size_and_leaves_zero_attention_areas_untouched():
    photo = Image.new("RGB", (300, 150), (40, 80, 120))
    overlay = make_overlay(photo, hot_spot(SIZE, slice(50, 70), slice(60, 80)), SIZE)
    assert overlay.size == (300, 150) and overlay.mode == "RGB"
    assert overlay.getpixel((2, 2)) == (40, 80, 120)  # far from the hot spot: unchanged
    cx, cy = 150, 75  # the hot spot is at the centre of the photo
    assert overlay.getpixel((cx, cy)) != (40, 80, 120)  # at the hot spot: recoloured


def test_overlay_is_scaled_down_for_big_photos_with_the_same_shape():
    overlay = make_overlay(Image.new("RGB", (2000, 1000), (10, 10, 10)), hot_spot(SIZE, slice(0, 10), slice(0, 10)), SIZE)
    assert max(overlay.size) == 512 and overlay.size == (512, 256)


def test_attention_in_the_padding_is_not_drawn_on_the_photo():
    photo = Image.new("RGB", (400, 100), (90, 90, 90))  # very wide: the model saw padding above and below
    width, height, left, top = letterbox_geometry(photo.size, SIZE)
    assert top > 10
    cam = np.zeros((SIZE, SIZE), dtype=np.float32)
    cam[:top, :] = 1.0  # all attention is in the top padding
    overlay = make_overlay(photo, cam, SIZE)
    assert np.array_equal(np.asarray(overlay), np.asarray(photo))  # nothing from the padding leaks onto the photo


def test_overlay_follows_the_exif_rotation_like_the_model_does():
    base = Image.new("RGB", (200, 100), (30, 60, 90))
    exif = Image.Exif()
    exif[0x0112] = 6  # "rotate 90 degrees": a viewer shows this 200x100 file as 100x200
    buffer = io.BytesIO()
    base.save(buffer, format="JPEG", exif=exif)
    rotated = Image.open(io.BytesIO(buffer.getvalue()))
    assert make_overlay(rotated, hot_spot(SIZE, slice(0, 5), slice(0, 5)), SIZE).size == (100, 200)


def test_encoded_overlay_is_a_small_valid_jpeg():
    image = Image.new("RGB", (512, 384), (120, 60, 30))
    data = base64.b64decode(encode_jpeg_base64(image))
    decoded = Image.open(io.BytesIO(data))
    assert decoded.format == "JPEG" and decoded.size == (512, 384)
    assert len(data) < 200_000


def test_colour_scale_runs_from_blue_to_red():
    low, high = jet_colors(np.array([0.0, 1.0]))
    assert low[2] > low[0] and high[0] > high[2]
    assert jet_colors(np.array([-5.0, 7.0])).min() >= 0 and jet_colors(np.array([-5.0, 7.0])).max() <= 1


def test_the_label_users_see_is_the_required_wording():
    assert gradcam.LABEL == "AI attention visualisation — not a diagnosis or proof of correctness."
    assert any("not a diagnosis" in text for text in gradcam.EXPLANATION_LIMITATIONS)
