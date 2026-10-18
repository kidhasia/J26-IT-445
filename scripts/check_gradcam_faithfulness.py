"""Sanity checks that the Grad-CAM maps really come from the trained model (aggregates only; no ids or images).

1. DELETION TEST. Blank the 13 of 64 grid cells (about 20%) with the highest attention and see how much the
   predicted class's probability falls. Compare with blanking 13 RANDOM cells (average of 10 draws). If the maps
   reflect what the model uses, blanking highlighted cells should hurt more than blanking random cells.
2. RANDOMISATION TEST (Adebayo et al. 2018). Compare maps from the trained model with maps from (a) the same
   architecture with fully random weights and (b) the trained model with only the final classifier re-randomised.
   If maps depended on the image alone (like an edge detector) they would not change; they should change.

Runs on the held-out TEST split of a training run. It does not train or tune anything.

Usage:  .venv/bin/python scripts/check_gradcam_faithfulness.py RUN_DIR METADATA_CSV IMAGES_DIR
"""

import copy
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import torch  # noqa: E402

from lumi.ml.gradcam import ExplanationEmpty, compute_grad_cam, find_target_layer  # noqa: E402
from lumi.ml.skin_data import CLASSES, load_samples, make_splits, resolve_duplicates  # noqa: E402
from lumi.ml.skin_model import build_model, load_checkpoint, pick_device, to_tensor  # noqa: E402
from lumi.ml.train_skin import build_image_cache  # noqa: E402

GRID, MASK_CELLS, RANDOM_DRAWS, ROUNDS = 8, 13, 10, 2000


def cell_scores(cam: np.ndarray) -> np.ndarray:
    size = cam.shape[0] // GRID
    return cam.reshape(GRID, size, GRID, size).mean(axis=(1, 3)).ravel()


def cell_mask(cells: np.ndarray, size: int, device) -> torch.Tensor:
    grid = np.zeros(GRID * GRID, dtype=np.float32)
    grid[cells] = 1.0
    mask = np.kron(grid.reshape(GRID, GRID), np.ones((size // GRID, size // GRID), dtype=np.float32))
    return torch.from_numpy(mask)[None, None].to(device)


def class_probability(model, x, index: int) -> float:
    with torch.no_grad():
        return float(torch.softmax(model(x), dim=1)[0, index])


def interval(values) -> str:
    low, high = np.percentile(values, [2.5, 97.5])
    return f"{low:+.3f} to {high:+.3f}"


def main(run_dir: Path, metadata: Path, images: Path) -> int:
    config = json.loads((run_dir / "config.json").read_text())["training_config"]
    checkpoint = load_checkpoint(run_dir / "checkpoint.pt")
    size = checkpoint["image_size"]
    arch = checkpoint["arch"]
    samples, _ = resolve_duplicates(load_samples(metadata, images))
    split = make_splits(samples, config["seed"], config["n_folds"], config["test_fold"], config["val_fold"])
    indices = [i for i, s in enumerate(samples) if split[s.img_id] == "test"]
    digest = hashlib.sha256("\n".join(s.img_id for s in samples).encode()).hexdigest()[:12]
    arrays = build_image_cache(samples, size, run_dir.parent / "cache" / f"images_{size}_{digest}.npy")

    device = pick_device(None)
    trained = build_model(arch, len(CLASSES), pretrained=False)
    trained.load_state_dict(checkpoint["state_dict"])
    trained.to(device).eval()
    name, layer = find_target_layer(trained, arch)

    torch.manual_seed(0)
    random_model = build_model(arch, len(CLASSES), pretrained=False).to(device).eval()
    head_random = copy.deepcopy(trained)
    torch.manual_seed(1)
    head_random.classifier.reset_parameters()
    head_random.to(device).eval()
    random_name, random_layer = find_target_layer(random_model, arch)
    head_name, head_layer = find_target_layer(head_random, arch)

    rng = np.random.default_rng(0)
    drop_cam, drop_random, flipped_cam, flipped_random = [], [], [], []
    corr_random, corr_head, empty_random, empty_head, patients = [], [], 0, 0, []
    skipped = 0
    for position, index in enumerate(indices):
        x = to_tensor(arrays[index]).unsqueeze(0).to(device)
        try:
            out = compute_grad_cam(trained, x, layer, name)
        except ExplanationEmpty:
            skipped += 1
            continue
        scores = cell_scores(out.cam)
        p0 = float(out.probabilities[out.class_index])
        top = np.argsort(-scores)[:MASK_CELLS]
        masked = x * (1.0 - cell_mask(top, size, device))
        p_cam = class_probability(trained, masked, out.class_index)
        random_ps = [class_probability(trained, x * (1.0 - cell_mask(rng.choice(GRID * GRID, MASK_CELLS, replace=False), size, device)), out.class_index)
                     for _ in range(RANDOM_DRAWS)]
        drop_cam.append(p0 - p_cam)
        drop_random.append(p0 - float(np.mean(random_ps)))
        with torch.no_grad():
            flipped_cam.append(int(trained(masked).argmax(1).item() != out.class_index))
        patients.append(samples[index].patient_id)

        if position < 150:  # the randomisation test on the first 150 test images
            for model, lyr, lname, bucket, kind in ((random_model, random_layer, random_name, corr_random, "random"), (head_random, head_layer, head_name, corr_head, "head")):
                try:
                    other = compute_grad_cam(model, x, lyr, lname, class_index=out.class_index)
                    bucket.append(float(np.corrcoef(out.cam.ravel(), other.cam.ravel())[0, 1]))
                except ExplanationEmpty:
                    if kind == "random":
                        empty_random += 1
                    else:
                        empty_head += 1

    drop_cam, drop_random = np.array(drop_cam), np.array(drop_random)
    difference = drop_cam - drop_random
    by_patient = defaultdict(list)
    for row, patient in enumerate(patients):
        by_patient[patient].append(row)
    groups = list(by_patient.values())
    brng = np.random.default_rng(0)
    boot = [difference[np.concatenate([groups[j] for j in brng.integers(0, len(groups), len(groups))])].mean() for _ in range(ROUNDS)]

    print(f"Test images explained: {len(drop_cam)} of {len(indices)} (empty maps skipped: {skipped}); device {device}; layer {name}")
    print()
    print(f"DELETION TEST (blank the {MASK_CELLS} of {GRID * GRID} cells = {MASK_CELLS / (GRID * GRID):.0%} of the image)")
    print(f"  mean fall in the predicted class's probability, highlighted cells blanked: {drop_cam.mean():.3f}")
    print(f"  mean fall in the predicted class's probability, random cells blanked:      {drop_random.mean():.3f}")
    print(f"  paired difference (highlighted minus random): {difference.mean():+.3f}   95% interval (patient-level) {interval(boot)}")
    print(f"  images where blanking highlighted cells hurt more than random cells: {(difference > 0).mean():.1%}")
    print(f"  predicted class changed after blanking highlighted cells: {np.mean(flipped_cam):.1%}")
    print()
    print("RANDOMISATION TEST (correlation between the trained model's map and another model's map, first 150 test images)")
    print(f"  fully random weights:               mean correlation {np.mean(corr_random):+.3f} over {len(corr_random)} maps ({empty_random} empty)")
    print(f"  trained, classifier re-randomised:  mean correlation {np.mean(corr_head):+.3f} over {len(corr_head)} maps ({empty_head} empty)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])))
