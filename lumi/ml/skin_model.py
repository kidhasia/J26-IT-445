"""Model construction, image preprocessing and checkpoint I/O for the skin-lesion classifier.

Checkpoints hold only tensors and plain Python values and are loaded with weights_only=True,
so loading one cannot run arbitrary code. Only load checkpoints you trained yourself or trust.
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

MEAN = (0.485, 0.456, 0.406)  # ImageNet statistics, used by the pretrained backbones
STD = (0.229, 0.224, 0.225)
FILL_RGB = tuple(round(255 * m) for m in MEAN)  # becomes ~0 after normalisation
CHECKPOINT_FORMAT_VERSION = 1
REQUIRED_CHECKPOINT_KEYS = ("format_version", "arch", "classes", "image_size", "state_dict", "info")


class CheckpointError(Exception):
    """The checkpoint is missing, unreadable or not in the expected format."""


def letterbox_geometry(image_size: tuple[int, int], size: int) -> tuple[int, int, int, int]:
    """Where the photo sits inside the padded square: (width, height, left offset, top offset).
    Shared by letterbox() and the Grad-CAM overlay so both always agree on the geometry."""
    scale = size / max(image_size)
    new_width, new_height = max(1, round(image_size[0] * scale)), max(1, round(image_size[1] * scale))
    return new_width, new_height, (size - new_width) // 2, (size - new_height) // 2


def upright_rgb(image: Image.Image) -> Image.Image:
    """Apply the EXIF rotation and convert to RGB (the same first step the model's preprocessing uses)."""
    return ImageOps.exif_transpose(image).convert("RGB")


def letterbox(image: Image.Image, size: int) -> Image.Image:
    """Upright (EXIF), convert to RGB, scale the longest side to `size` and pad to a square.
    Nothing is cropped, so the whole photo stays visible."""
    image = upright_rgb(image)
    new_width, new_height, left, top = letterbox_geometry(image.size, size)
    resized = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (size, size), FILL_RGB)
    canvas.paste(resized, (left, top))
    return canvas


def to_tensor(rgb_uint8: np.ndarray):
    """HWC uint8 array -> normalised CHW float tensor."""
    import torch

    array = rgb_uint8.astype(np.float32) / 255.0
    array = (array - np.array(MEAN, dtype=np.float32)) / np.array(STD, dtype=np.float32)
    return torch.from_numpy(array.transpose(2, 0, 1).copy())


def pick_device(requested: str | None = None) -> str:
    import torch

    if requested and requested != "auto":
        return requested
    return "mps" if torch.backends.mps.is_available() else "cpu"


def build_model(arch: str, num_classes: int, pretrained: bool):
    import timm

    return timm.create_model(arch, pretrained=pretrained, num_classes=num_classes)


def save_checkpoint(path: Path, model, arch: str, classes: tuple[str, ...], image_size: int, info: dict) -> None:
    import torch

    payload = {
        "format_version": CHECKPOINT_FORMAT_VERSION,
        "arch": arch,
        "classes": list(classes),
        "image_size": image_size,
        "mean": list(MEAN),
        "std": list(STD),
        "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
        "info": info,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, path)


def load_checkpoint(path: Path) -> dict:
    import torch

    path = Path(path)
    if not path.is_file():
        raise CheckpointError("The checkpoint file does not exist.")
    try:
        payload = torch.load(path, map_location="cpu", weights_only=True)
    except Exception as exc:  # noqa: BLE001  (torch raises several types for damaged or unsafe files)
        raise CheckpointError("The checkpoint could not be loaded safely.") from exc
    if not isinstance(payload, dict) or any(key not in payload for key in REQUIRED_CHECKPOINT_KEYS):
        raise CheckpointError("The checkpoint is missing required fields.")
    if payload["format_version"] != CHECKPOINT_FORMAT_VERSION:
        raise CheckpointError("The checkpoint format version is not supported.")
    return payload
