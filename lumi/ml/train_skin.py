"""Fine-tune a pretrained image classifier on PAD-UFES-20 (6 skin-lesion classes).

Protocol (decided before any test-set number is seen):
- patient-level, stratified split (train / val / test), fixed seed;
- the validation split picks the best epoch;
- the test split is evaluated exactly ONCE, after training and epoch selection are finished;
- all outputs (checkpoint, config, metrics, log) go under --out-dir, never next to the source data.

Run:  .venv/bin/python -m lumi.ml.train_skin --metadata ... --images ... --out-dir models/skin_pad_ufes20
"""

import argparse
import copy
import csv
import hashlib
import json
import platform
import random
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from lumi.ml.skin_data import CLASS_NAMES, CLASSES, DataError, Sample, load_samples, make_splits, resolve_duplicates, split_summary
from lumi.ml.skin_model import (
    FILL_RGB,
    build_model,
    letterbox,
    pick_device,
    save_checkpoint,
    to_tensor,
)

DATASET_INFO = {
    "name": "PAD-UFES-20",
    "source": "Mendeley Data, doi:10.17632/zr7vgbcyr2.1 (version 1)",
    "licence": "CC BY 4.0",
    "citation": "Pacheco et al., Data in Brief 32:106221 (2020), doi:10.1016/j.dib.2020.106221",
}


@dataclass
class TrainConfig:
    metadata: Path
    images: Path
    out_dir: Path
    arch: str = "efficientnet_b0"
    pretrained: bool = True
    image_size: int = 256
    epochs: int = 12
    batch_size: int = 32
    learning_rate: float = 3e-4
    weight_decay: float = 1e-4
    seed: int = 42
    n_folds: int = 5
    test_fold: int = 0
    val_fold: int = 1
    device: str = "auto"
    cache_dir: Path | None = None  # where resized images are cached (must be outside the source data)


# ---------------------------------------------------------------- reproducibility helpers


def set_seed(seed: int) -> None:
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def git_state() -> dict:
    root = Path(__file__).resolve().parents[2]
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=True).stdout.strip())
        return {"commit": commit, "uncommitted_changes": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "uncommitted_changes": None}


def library_versions() -> dict:
    import sklearn
    import timm
    import torch

    return {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "timm": timm.__version__,
        "numpy": np.__version__,
        "scikit-learn": sklearn.__version__,
        "platform": platform.platform(),
    }


# ---------------------------------------------------------------- data


def build_image_cache(samples: list[Sample], size: int, cache_path: Path) -> np.ndarray:
    """Resize every image once (letterboxed to size x size) and keep the result in one uint8 array.
    The cache lives outside the source data; source images are only read."""
    if cache_path.is_file():
        cached = np.load(cache_path)
        if cached.shape == (len(samples), size, size, 3):
            return cached
    array = np.zeros((len(samples), size, size, 3), dtype=np.uint8)
    for index, sample in enumerate(samples):
        with Image.open(sample.path) as image:
            array[index] = np.asarray(letterbox(image, size))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache_path, array)
    return array


class SkinDataset:
    def __init__(self, images: np.ndarray, labels: np.ndarray, train: bool, size: int):
        from torchvision import transforms

        self.images, self.labels, self.train = images, labels, train
        self.augment = transforms.Compose(
            [
                transforms.RandomHorizontalFlip(),
                transforms.RandomVerticalFlip(),
                transforms.RandomRotation(20, fill=FILL_RGB),
                transforms.RandomResizedCrop(size, scale=(0.75, 1.0), ratio=(0.9, 1.1)),
                transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2, hue=0.02),
            ]
        )

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, index: int):
        array = self.images[index]
        if self.train:
            array = np.asarray(self.augment(Image.fromarray(array)))
        return to_tensor(array), int(self.labels[index])


# ---------------------------------------------------------------- metrics


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray, probabilities: np.ndarray | None, classes: tuple[str, ...] = CLASSES) -> dict:
    from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support, roc_auc_score

    labels = list(range(len(classes)))
    precision, recall, f1, support = precision_recall_fscore_support(y_true, y_pred, labels=labels, zero_division=0)
    present = support > 0  # macro averages use only classes that occur in this split
    roc_auc = None
    if probabilities is not None and present.all():
        # Float32 softmax outputs can sum to 1 only approximately; sklearn requires an exact-looking 1.
        probabilities = probabilities.astype(np.float64)
        probabilities = probabilities / probabilities.sum(axis=1, keepdims=True)
        try:
            roc_auc = round(float(roc_auc_score(y_true, probabilities, multi_class="ovr", average="macro", labels=labels)), 4)
        except ValueError:
            roc_auc = None
    return {
        "images": int(len(y_true)),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "balanced_accuracy": round(float(recall[present].mean()), 4),
        "macro_f1": round(float(f1[present].mean()), 4),
        "macro_roc_auc_ovr": roc_auc,
        "per_class": {
            name: {
                "precision": round(float(precision[i]), 4),
                "recall": round(float(recall[i]), 4),
                "f1": round(float(f1[i]), 4),
                "support": int(support[i]),
            }
            for i, name in enumerate(classes)
        },
        "confusion_matrix": {"rows_are_true_classes_columns_are_predicted": list(classes), "matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist()},
    }


def predict(model, dataset: SkinDataset, device: str, batch_size: int) -> tuple[np.ndarray, np.ndarray]:
    import torch

    model.eval()
    loader = torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=False)
    all_probs = []
    with torch.inference_mode():
        for images, _ in loader:
            all_probs.append(torch.softmax(model(images.to(device)), dim=1).cpu().numpy())
    probabilities = np.concatenate(all_probs) if all_probs else np.zeros((0, len(CLASSES)))
    return probabilities.argmax(axis=1), probabilities


# ---------------------------------------------------------------- training


def run_training(config: TrainConfig, log=print) -> Path:
    import torch

    started = time.time()
    set_seed(config.seed)
    device = pick_device(config.device)
    samples, duplicate_report = resolve_duplicates(load_samples(config.metadata, config.images))
    log(f"Duplicate handling: {duplicate_report['duplicate_groups']} duplicate group(s); "
        f"dropped {duplicate_report['images_dropped_because_labels_conflict']} conflicting-label and "
        f"{duplicate_report['images_dropped_as_redundant_copies']} redundant image(s); using {len(samples)}.")
    assignment = make_splits(samples, config.seed, config.n_folds, config.test_fold, config.val_fold)
    counts = split_summary(samples, assignment)
    log(f"Samples: {len(samples)}. Split (images/patients): "
        + ", ".join(f"{name} {counts[name]['images']}/{counts[name]['patients']}" for name in ("train", "val", "test")))

    cache_dir = config.cache_dir or config.out_dir / "cache"
    sample_digest = hashlib.sha256("\n".join(s.img_id for s in samples).encode()).hexdigest()[:12]  # cache is tied to exactly these samples
    images = build_image_cache(samples, config.image_size, cache_dir / f"images_{config.image_size}_{sample_digest}.npy")
    labels = np.array([CLASSES.index(s.label) for s in samples])
    indices = {name: np.array([i for i, s in enumerate(samples) if assignment[s.img_id] == name]) for name in ("train", "val", "test")}
    datasets = {name: SkinDataset(images[idx], labels[idx], train=(name == "train"), size=config.image_size) for name, idx in indices.items()}

    model = build_model(config.arch, len(CLASSES), config.pretrained).to(device)
    train_counts = np.bincount(labels[indices["train"]], minlength=len(CLASSES))
    class_weights = (len(indices["train"]) / (len(CLASSES) * np.maximum(train_counts, 1))) ** 0.5  # tempered inverse frequency
    criterion = torch.nn.CrossEntropyLoss(weight=torch.tensor(class_weights, dtype=torch.float32, device=device))
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, config.epochs))
    generator = torch.Generator().manual_seed(config.seed)
    loader = torch.utils.data.DataLoader(datasets["train"], batch_size=config.batch_size, shuffle=True, generator=generator, drop_last=len(datasets["train"]) > config.batch_size)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = config.out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    best = {"macro_f1": -1.0, "epoch": 0, "state": None}
    history = []
    for epoch in range(1, config.epochs + 1):
        epoch_start = time.time()
        model.train()
        total_loss = 0.0
        for batch_images, batch_labels in loader:
            optimizer.zero_grad()
            loss = criterion(model(batch_images.to(device)), batch_labels.to(device))
            loss.backward()
            optimizer.step()
            total_loss += float(loss.item()) * len(batch_labels)
        scheduler.step()
        val_pred, val_prob = predict(model, datasets["val"], device, config.batch_size)
        val_metrics = compute_metrics(labels[indices["val"]], val_pred, val_prob)
        row = {"epoch": epoch, "train_loss": round(total_loss / len(datasets["train"]), 4), "val_macro_f1": val_metrics["macro_f1"],
               "val_accuracy": val_metrics["accuracy"], "seconds": round(time.time() - epoch_start, 1)}
        history.append(row)
        log(f"epoch {epoch:>2}/{config.epochs}  train_loss {row['train_loss']:.4f}  val_macro_f1 {row['val_macro_f1']:.4f}  val_acc {row['val_accuracy']:.4f}  ({row['seconds']}s)")
        if val_metrics["macro_f1"] > best["macro_f1"]:
            best = {"macro_f1": val_metrics["macro_f1"], "epoch": epoch, "state": copy.deepcopy({k: v.detach().cpu() for k, v in model.state_dict().items()}), "val_metrics": val_metrics}

    # Training and epoch selection are finished. Only now is the test split touched, once.
    model.load_state_dict(best["state"])
    test_pred, test_prob = predict(model, datasets["test"], device, config.batch_size)
    test_metrics = compute_metrics(labels[indices["test"]], test_pred, test_prob)
    majority = int(np.argmax(train_counts))
    baseline = compute_metrics(labels[indices["test"]], np.full(len(indices["test"]), majority), None)

    metrics = {
        "validation": {**best["val_metrics"], "best_epoch": best["epoch"],
                       "note": "Used to choose the best epoch, so this is NOT an unbiased estimate of performance."},
        "test": {**test_metrics, "note": "Evaluated once, after all training and epoch-selection decisions were final."},
        "baseline_always_predict_majority_class_on_test": {"class": CLASSES[majority], **baseline},
    }
    info = {
        "run_id": run_id,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": DATASET_INFO,
        "pretrained_backbone": config.pretrained,
        "seed": config.seed,
        "best_epoch": best["epoch"],
        "validation_macro_f1": best["macro_f1"],
        "test_macro_f1": test_metrics["macro_f1"],
        "test_images": test_metrics["images"],
    }
    save_checkpoint(run_dir / "checkpoint.pt", model, config.arch, CLASSES, config.image_size, info)
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    (run_dir / "classes.json").write_text(json.dumps({code: CLASS_NAMES[code] for code in CLASSES}, indent=2) + "\n")
    with (run_dir / "training_log.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(history[0]))
        writer.writeheader()
        writer.writerows(history)
    (run_dir / "config.json").write_text(json.dumps({
        "run_id": run_id,
        "training_config": {k: str(v) if isinstance(v, Path) else v for k, v in asdict(config).items()},
        "device_used": device,
        "dataset": DATASET_INFO,
        "split_counts": counts,
        "duplicate_handling": duplicate_report,
        "class_weights": {name: round(float(w), 4) for name, w in zip(CLASSES, class_weights)},
        "git": git_state(),
        "versions": library_versions(),
        "total_seconds": round(time.time() - started, 1),
        "notes": ["GPU (MPS) training is not bit-for-bit reproducible even with a fixed seed."],
    }, indent=2) + "\n")
    log(f"Best epoch {best['epoch']} (validation macro-F1 {best['macro_f1']:.4f}). Test macro-F1 {test_metrics['macro_f1']:.4f} on {test_metrics['images']} images.")
    log(f"Saved to {run_dir}")
    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fine-tune a skin-lesion classifier on PAD-UFES-20.")
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--images", required=True, type=Path, help="Folder containing the extracted images.")
    parser.add_argument("--out-dir", required=True, type=Path, help="Where runs are saved (must not be inside the dataset folder).")
    parser.add_argument("--arch", default="efficientnet_b0")
    parser.add_argument("--no-pretrained", action="store_true", help="Train from random weights (only for tests).")
    parser.add_argument("--image-size", type=int, default=256)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default="auto", help="auto, mps or cpu")
    args = parser.parse_args(argv)
    try:
        args.out_dir.resolve().relative_to(args.images.resolve())
        print("ERROR: --out-dir must not be inside the image folder; source data is never modified.", file=sys.stderr)
        return 2
    except ValueError:
        pass
    try:
        run_training(TrainConfig(metadata=args.metadata, images=args.images, out_dir=args.out_dir, arch=args.arch,
                                 pretrained=not args.no_pretrained, image_size=args.image_size, epochs=args.epochs,
                                 batch_size=args.batch_size, learning_rate=args.learning_rate, seed=args.seed, device=args.device))
    except DataError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
