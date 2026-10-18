"""Offline predictions for a trained run, made the same way training evaluated them."""

import hashlib
from pathlib import Path

import numpy as np

from lumi.ml.skin_model import build_model, load_checkpoint, pick_device
from lumi.ml.train_skin import SkinDataset, build_image_cache, predict


def offline_probabilities(run_dir: Path, samples, indices: list[int], device: str | None = None) -> np.ndarray:
    """Class probabilities for samples[indices]: cached uint8 arrays -> eval dataset -> checkpoint model."""
    checkpoint = load_checkpoint(run_dir / "checkpoint.pt")
    size = checkpoint["image_size"]
    digest = hashlib.sha256("\n".join(s.img_id for s in samples).encode()).hexdigest()[:12]
    arrays = build_image_cache(samples, size, run_dir.parent / "cache" / f"images_{size}_{digest}.npy")[indices]
    model = build_model(checkpoint["arch"], len(checkpoint["classes"]), pretrained=False)
    model.load_state_dict(checkpoint["state_dict"])
    device = pick_device(device)
    _, probabilities = predict(
        model.to(device), SkinDataset(arrays, np.zeros(len(indices), dtype=int), train=False, size=size), device, 32
    )
    return probabilities
