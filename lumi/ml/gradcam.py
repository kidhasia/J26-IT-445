"""Grad-CAM for the skin-lesion classifier: which image regions pushed the model toward its predicted class.

Method (Selvaraju et al., ICCV 2017): take the last convolutional feature map, weight each channel by the
average gradient of the class score with respect to that channel, add the channels up, keep only positive
evidence (ReLU) and enlarge the result to the input size.

For this EfficientNet-B0 the layer is `bn2` (1280 channels, 8 x 8 for a 256 px input). The classifier is
"average over the map, then one linear layer", so Grad-CAM here equals the classic Class Activation Map; the tests
check the implementation against that independent formula.

Honest limits (also shown to users): the map is only 8 x 8 and is enlarged, so it is coarse; it describes what the
MODEL used, not what is medically important; and a clear-looking map does not mean the prediction is right.
"""

import base64
import io
from dataclasses import dataclass

import numpy as np
from PIL import Image

from lumi.ml.skin_model import letterbox_geometry, upright_rgb

LABEL = "AI attention visualisation — not a diagnosis or proof of correctness."
HOW_TO_READ = (
    "Warmer colours (yellow to red) mark image areas that raised the model's score for the class it chose; areas left "
    "unchanged had little influence. The map is coarse (8 by 8 cells enlarged), so it shows broad areas, not outlines."
)
EXPLANATION_LIMITATIONS = [
    "It shows what influenced this model's score, not what is medically important. A model can rely on irrelevant "
    "things such as skin texture, image borders, rulers or lighting and still look confident.",
    "A heatmap that looks sensible does not show that the prediction is correct, and an odd one does not show that it is wrong.",
    "It explains only the single highest-scoring class, and only for this one image.",
    "It is not a diagnosis and must not be used as clinical evidence.",
]
OVERLAY_MAX_SIDE = 512
OVERLAY_MAX_OPACITY = 0.65
JPEG_QUALITY = 85


class ExplanationError(Exception):
    """The explanation could not be produced. The prediction itself is unaffected."""


class ExplanationUnsupported(ExplanationError):
    """This model architecture has no known Grad-CAM target layer."""


class ExplanationEmpty(ExplanationError):
    """The attention map was empty (no positive evidence), so there is nothing honest to draw."""


@dataclass(frozen=True)
class GradCamOutput:
    probabilities: np.ndarray  # softmax scores from the SAME forward pass the map was computed from
    class_index: int
    cam: np.ndarray  # float32, same height and width as the model input, values in [0, 1], max is exactly 1
    layer_name: str
    grid: tuple[int, int]  # size of the feature map the map was built from (before enlarging), e.g. (8, 8)


def find_target_layer(model, arch: str):
    """The last feature map before the classifier head. Only architectures checked by hand are supported."""
    import torch

    if arch == "efficientnet_b0" and hasattr(model, "bn2"):
        return "bn2", model.bn2
    blocks = getattr(model, "blocks", None)
    if isinstance(blocks, torch.nn.Sequential) and len(blocks) > 0 and hasattr(model, "classifier"):
        return "blocks[-1]", blocks[-1]
    raise ExplanationUnsupported(f"No Grad-CAM target layer is defined for architecture '{arch}'.")


def compute_grad_cam(model, input_tensor, layer, layer_name: str, class_index: int | None = None) -> GradCamOutput:
    """Run one forward and one backward pass. `input_tensor` is a normalised (1, 3, H, W) tensor on the model's device.
    Probabilities and the map come from the same forward pass, so the map always belongs to the reported prediction."""
    import torch
    import torch.nn.functional as functional

    stored: dict = {}
    handle = layer.register_forward_hook(lambda _module, _inputs, output: stored.__setitem__("activation", output))
    try:
        with torch.enable_grad():
            x = input_tensor.detach().clone().requires_grad_(True)
            logits = model(x)
            probabilities = torch.softmax(logits.detach(), dim=1)[0].cpu().numpy()
            index = int(probabilities.argmax()) if class_index is None else int(class_index)
            if not 0 <= index < logits.shape[1]:
                raise ExplanationError("The requested class does not exist.")
            activation = stored.get("activation")
            if activation is None:
                raise ExplanationError("The target layer produced no output.")
            gradients = torch.autograd.grad(logits[0, index], activation)[0]
        grid = (int(activation.shape[2]), int(activation.shape[3]))
        weights = gradients.mean(dim=(2, 3), keepdim=True)  # one importance weight per channel
        cam = torch.relu((weights * activation.detach()).sum(dim=1, keepdim=True))
        cam = functional.interpolate(cam, size=tuple(input_tensor.shape[2:]), mode="bilinear", align_corners=False)
        cam = cam[0, 0].cpu().numpy().astype(np.float32)
    except ExplanationError:
        raise
    except Exception as exc:  # noqa: BLE001  (torch raises many types when a model cannot be differentiated)
        raise ExplanationError("The attention map could not be computed for this model.") from exc
    finally:
        handle.remove()

    if not np.isfinite(cam).all():
        raise ExplanationError("The attention map contained invalid numbers.")
    peak = float(cam.max())
    if peak <= 1e-12:
        raise ExplanationEmpty("The model found no positive evidence for this class in the image, so no map is shown.")
    return GradCamOutput(probabilities=probabilities, class_index=index, cam=cam / peak, layer_name=layer_name, grid=grid)


def jet_colors(values: np.ndarray) -> np.ndarray:
    """Blue (low) to red (high) colour scale for values in [0, 1]; returns float RGB in [0, 1]."""
    v = np.clip(values, 0.0, 1.0)
    red = np.clip(1.5 - np.abs(4 * v - 3), 0, 1)
    green = np.clip(1.5 - np.abs(4 * v - 2), 0, 1)
    blue = np.clip(1.5 - np.abs(4 * v - 1), 0, 1)
    return np.stack([red, green, blue], axis=-1)


def make_overlay(original: Image.Image, cam: np.ndarray, model_size: int, max_side: int = OVERLAY_MAX_SIDE) -> Image.Image:
    """Draw the map on the user's own image. The padding the model saw is cut away first, so the map lines up with
    the photo. Where the map is 0 the photo is left unchanged; stronger attention is blended with more colour."""
    photo = upright_rgb(original)
    width, height, left, top = letterbox_geometry(photo.size, model_size)
    inside = cam[top : top + height, left : left + width]  # drop the padding the model saw
    scale = min(1.0, max_side / max(photo.size))
    out_size = (max(1, round(photo.width * scale)), max(1, round(photo.height * scale)))
    base = np.asarray(photo.resize(out_size, Image.Resampling.LANCZOS), dtype=np.float32) / 255.0
    heat = np.asarray(Image.fromarray(inside.astype(np.float32), mode="F").resize(out_size, Image.Resampling.BILINEAR))
    heat = np.clip(heat, 0.0, 1.0)
    opacity = (OVERLAY_MAX_OPACITY * heat)[..., None]
    blended = (1.0 - opacity) * base + opacity * jet_colors(heat)
    return Image.fromarray(np.clip(blended * 255.0 + 0.5, 0, 255).astype(np.uint8), mode="RGB")


def encode_jpeg_base64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return base64.b64encode(buffer.getvalue()).decode("ascii")
