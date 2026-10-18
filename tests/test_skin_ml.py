"""Tests for the skin-lesion data loading, splitting, metrics, checkpoints and training loop.

All data is generated: 6 classes, each drawn in a different colour so a tiny model can learn it.
This is SYNTHETIC test data. It verifies the code, not any medical claim.
"""

import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import torch
from PIL import Image

from lumi.ml import train_skin
from lumi.ml.skin_data import CLASSES, DataError, Sample, find_images, load_samples, make_splits, resolve_duplicates, split_summary, verify_no_patient_leakage
from lumi.ml.skin_model import CheckpointError, FILL_RGB, build_model, letterbox, load_checkpoint, save_checkpoint, to_tensor
from lumi.ml.train_skin import TrainConfig, compute_metrics, run_training

COLORS = {"ACK": (200, 40, 40), "BCC": (40, 200, 40), "MEL": (40, 40, 200), "NEV": (200, 200, 40), "SCC": (200, 40, 200), "SEK": (40, 200, 200)}
TINY_ARCH = "mobilenetv3_small_050"


def make_dataset(root: Path, patients_per_class: int = 12, images_per_patient: int = 1, size=(48, 36)) -> tuple[Path, Path]:
    """Write fake images plus a metadata.csv with the real PAD-UFES-20 column names."""
    images = root / "images" / "part_1"
    images.mkdir(parents=True)
    rows = []
    for class_index, label in enumerate(CLASSES):
        for p in range(patients_per_class):
            patient = f"PAT_{class_index * 100 + p}"
            for k in range(images_per_patient):
                img_id = f"{patient}_{k}.png"
                shade = (p * 7 + k * 3) % 40
                color = tuple(min(255, c + shade) for c in COLORS[label])
                Image.new("RGB", size, color).save(images / img_id)
                rows.append({"patient_id": patient, "lesion_id": f"{patient}_L{k}", "age": "40", "diagnostic": label, "img_id": img_id})
    metadata = root / "metadata.csv"
    with metadata.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["patient_id", "lesion_id", "age", "diagnostic", "img_id"])
        writer.writeheader()
        writer.writerows(rows)
    return metadata, root / "images"


def fingerprint(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in sorted(root.rglob("*")) if p.is_file()}


# ---------------------------------------------------------------- loading


def test_load_samples_counts_and_order(tmp_path):
    metadata, images = make_dataset(tmp_path)
    samples = load_samples(metadata, images)
    assert len(samples) == 72
    assert [s.img_id for s in samples] == sorted(s.img_id for s in samples)
    assert {s.label for s in samples} == set(CLASSES)


def test_missing_required_column_is_reported_with_available_columns(tmp_path):
    metadata, images = make_dataset(tmp_path)
    metadata.write_text(metadata.read_text().replace("diagnostic", "dx", 1))
    with pytest.raises(DataError) as excinfo:
        load_samples(metadata, images)
    assert "diagnostic" in str(excinfo.value) and "dx" in str(excinfo.value)


def test_unknown_diagnosis_is_rejected(tmp_path):
    metadata, images = make_dataset(tmp_path)
    metadata.write_text(metadata.read_text().replace(",ACK,", ",XYZ,", 1))
    with pytest.raises(DataError, match="outside"):
        load_samples(metadata, images)


def test_metadata_row_without_image_is_rejected(tmp_path):
    metadata, images = make_dataset(tmp_path)
    next(images.rglob("*.png")).unlink()
    with pytest.raises(DataError, match="no matching image"):
        load_samples(metadata, images)


def test_duplicate_file_names_in_different_folders_are_rejected(tmp_path):
    metadata, images = make_dataset(tmp_path)
    other = images / "part_2"
    other.mkdir()
    first = next((images / "part_1").glob("*.png"))
    (other / first.name).write_bytes(first.read_bytes())
    with pytest.raises(DataError, match="share the same file name"):
        find_images(images)


def test_missing_paths_are_data_errors(tmp_path):
    with pytest.raises(DataError):
        load_samples(tmp_path / "nope.csv", tmp_path)
    metadata, _ = make_dataset(tmp_path)
    with pytest.raises(DataError):
        load_samples(metadata, tmp_path / "no_such_folder")


# ---------------------------------------------------------------- duplicates


def test_duplicate_rule_keeps_one_consistent_copy_and_drops_conflicting_ones(tmp_path):
    metadata, images = make_dataset(tmp_path, patients_per_class=3)
    samples = load_samples(metadata, images)
    by_label = {label: [s for s in samples if s.label == label] for label in CLASSES}
    # same bytes, same label -> keep one
    a, b = by_label["ACK"][0], by_label["ACK"][1]
    b.path.write_bytes(a.path.read_bytes())
    # same bytes, different labels -> drop both
    c, d = by_label["BCC"][0], by_label["MEL"][0]
    d.path.write_bytes(c.path.read_bytes())
    kept, report = resolve_duplicates(samples)
    kept_ids = {s.img_id for s in kept}
    assert (a.img_id in kept_ids) != (b.img_id in kept_ids)  # exactly one of the pair survives
    assert min(a.img_id, b.img_id) in kept_ids  # the first by img_id
    assert c.img_id not in kept_ids and d.img_id not in kept_ids
    assert report["duplicate_groups"] == 2 and report["groups_with_conflicting_labels"] == 1
    assert report["images_dropped_as_redundant_copies"] == 1 and report["images_dropped_because_labels_conflict"] == 2
    assert report["images_before"] == len(samples) and report["images_after"] == len(samples) - 3


def test_no_duplicates_means_nothing_is_dropped(tmp_path):
    metadata, images = make_dataset(tmp_path)
    samples = load_samples(metadata, images)
    kept, report = resolve_duplicates(samples)
    assert kept == samples and report["duplicate_groups"] == 0


# ---------------------------------------------------------------- splitting


def test_splits_are_patient_level_complete_and_reproducible(tmp_path):
    metadata, images = make_dataset(tmp_path, images_per_patient=3)
    samples = load_samples(metadata, images)
    split = make_splits(samples, seed=42)
    assert set(split.values()) == {"train", "val", "test"} and len(split) == len(samples)
    patients = {name: {s.patient_id for s in samples if split[s.img_id] == name} for name in ("train", "val", "test")}
    assert not (patients["train"] & patients["val"]) and not (patients["train"] & patients["test"]) and not (patients["val"] & patients["test"])
    assert make_splits(samples, seed=42) == split  # same seed, same split
    assert make_splits(samples, seed=43) != split  # different seed, different split


def test_every_class_appears_in_every_split(tmp_path):
    metadata, images = make_dataset(tmp_path)
    samples = load_samples(metadata, images)
    summary = split_summary(samples, make_splits(samples, seed=1))
    for name in ("train", "val", "test"):
        assert all(count > 0 for count in summary[name]["classes"].values())
    assert sum(summary[name]["images"] for name in summary) == len(samples)


def test_leakage_check_detects_a_shared_patient(tmp_path):
    shared = [Sample("a.png", "P1", "L1", "ACK", tmp_path), Sample("b.png", "P1", "L1", "ACK", tmp_path)]
    with pytest.raises(DataError, match="leakage"):
        verify_no_patient_leakage(shared, {"a.png": "train", "b.png": "test"})


def test_split_folds_must_differ(tmp_path):
    metadata, images = make_dataset(tmp_path)
    with pytest.raises(DataError):
        make_splits(load_samples(metadata, images), test_fold=1, val_fold=1)


# ---------------------------------------------------------------- preprocessing and metrics


def test_letterbox_keeps_aspect_ratio_and_pads_with_neutral_colour():
    tall = Image.new("RGB", (20, 40), (255, 0, 0))
    out = letterbox(tall, 64)
    assert out.size == (64, 64)
    assert out.getpixel((32, 32)) == (255, 0, 0)  # the photo is in the middle
    assert out.getpixel((2, 32)) == FILL_RGB  # padding on the left, not stretched content


@pytest.mark.parametrize("mode", ["RGBA", "L", "P"])
def test_letterbox_accepts_other_image_modes(mode):
    assert letterbox(Image.new(mode, (30, 20)), 32).mode == "RGB"


def test_to_tensor_shape_and_normalisation():
    tensor = to_tensor(np.full((8, 8, 3), FILL_RGB, dtype=np.uint8))
    assert tuple(tensor.shape) == (3, 8, 8)
    assert tensor.abs().max() < 0.02  # the padding colour normalises to about zero


def test_compute_metrics_matches_hand_calculation():
    y_true = np.array([0, 0, 1, 1, 2, 2])
    y_pred = np.array([0, 1, 1, 1, 2, 0])
    metrics = compute_metrics(y_true, y_pred, None, classes=("A", "B", "C"))
    assert metrics["accuracy"] == 0.6667 and metrics["balanced_accuracy"] == 0.6667
    assert metrics["macro_f1"] == 0.6556
    assert metrics["per_class"]["A"] == {"precision": 0.5, "recall": 0.5, "f1": 0.5, "support": 2}
    assert metrics["per_class"]["B"]["f1"] == 0.8
    assert metrics["confusion_matrix"]["matrix"] == [[1, 1, 0], [0, 2, 0], [1, 0, 1]]
    assert metrics["macro_roc_auc_ovr"] is None


def test_macro_metrics_ignore_classes_absent_from_the_split():
    y_true, y_pred = np.array([0, 0, 1, 1, 2, 2]), np.array([0, 1, 1, 1, 2, 0])
    with_absent = compute_metrics(y_true, y_pred, None, classes=("A", "B", "C", "D"))
    assert with_absent["macro_f1"] == 0.6556
    assert with_absent["per_class"]["D"]["support"] == 0


def test_roc_auc_is_computed_when_probabilities_are_given():
    y_true = np.array([0, 1, 2, 0, 1, 2])
    probabilities = np.eye(3)[y_true] * 0.7 + 0.1  # perfectly ranked, rows sum to exactly 1
    assert compute_metrics(y_true, probabilities.argmax(1), probabilities, classes=("A", "B", "C"))["macro_roc_auc_ovr"] == 1.0
    sloppy = probabilities * 1.0001  # rows sum to slightly more than 1, like float rounding
    assert compute_metrics(y_true, sloppy.argmax(1), sloppy, classes=("A", "B", "C"))["macro_roc_auc_ovr"] == 1.0


# ---------------------------------------------------------------- checkpoints


def tiny_model():
    torch.manual_seed(0)
    return build_model(TINY_ARCH, len(CLASSES), pretrained=False)


def test_checkpoint_round_trip(tmp_path):
    model = tiny_model()
    path = tmp_path / "ckpt.pt"
    save_checkpoint(path, model, TINY_ARCH, CLASSES, 64, {"run_id": "t", "test_macro_f1": 0.5})
    loaded = load_checkpoint(path)
    assert loaded["classes"] == list(CLASSES) and loaded["image_size"] == 64 and loaded["info"]["run_id"] == "t"
    rebuilt = build_model(loaded["arch"], len(loaded["classes"]), pretrained=False)
    rebuilt.load_state_dict(loaded["state_dict"])
    x = torch.randn(2, 3, 64, 64)
    assert torch.allclose(model.eval()(x), rebuilt.eval()(x), atol=1e-6)


def test_missing_and_garbage_checkpoints_are_errors(tmp_path):
    with pytest.raises(CheckpointError):
        load_checkpoint(tmp_path / "nope.pt")
    garbage = tmp_path / "garbage.pt"
    garbage.write_bytes(b"not a checkpoint")
    with pytest.raises(CheckpointError):
        load_checkpoint(garbage)


def test_checkpoint_with_executable_pickle_is_refused(tmp_path):
    class Sneaky:
        def __reduce__(self):
            return (print, ("this must never run",))

    path = tmp_path / "evil.pt"
    torch.save({"format_version": 1, "payload": Sneaky()}, path)
    with pytest.raises(CheckpointError):
        load_checkpoint(path)


def test_checkpoint_missing_fields_is_an_error(tmp_path):
    path = tmp_path / "partial.pt"
    torch.save({"format_version": 1}, path)
    with pytest.raises(CheckpointError, match="missing required fields"):
        load_checkpoint(path)


# ---------------------------------------------------------------- training loop (tiny, on fake data)


def small_config(tmp_path, metadata, images, **overrides) -> TrainConfig:
    values = dict(metadata=metadata, images=images, out_dir=tmp_path / "runs", arch=TINY_ARCH, pretrained=False,
                  image_size=64, epochs=2, batch_size=16, device="cpu")
    values.update(overrides)
    return TrainConfig(**values)


def test_training_run_writes_all_outputs_and_never_touches_source_data(tmp_path):
    metadata, images = make_dataset(tmp_path / "data")
    before = fingerprint(tmp_path / "data")
    logged = []
    run_dir = run_training(small_config(tmp_path, metadata, images), log=logged.append)
    assert fingerprint(tmp_path / "data") == before  # source data untouched
    assert not run_dir.resolve().is_relative_to((tmp_path / "data").resolve())
    for name in ("checkpoint.pt", "metrics.json", "config.json", "training_log.csv", "classes.json"):
        assert (run_dir / name).is_file()
    metrics = json.loads((run_dir / "metrics.json").read_text())
    assert "NOT an unbiased estimate" in metrics["validation"]["note"]
    assert "once" in metrics["test"]["note"]
    assert metrics["test"]["images"] > 0 and 0.0 <= metrics["test"]["macro_f1"] <= 1.0
    assert "baseline_always_predict_majority_class_on_test" in metrics
    config = json.loads((run_dir / "config.json").read_text())
    assert config["training_config"]["seed"] == 42 and config["dataset"]["licence"] == "CC BY 4.0"
    assert config["versions"]["torch"] and "commit" in config["git"]
    assert load_checkpoint(run_dir / "checkpoint.pt")["info"]["test_macro_f1"] == metrics["test"]["macro_f1"]
    assert sum(config["split_counts"][s]["images"] for s in ("train", "val", "test")) == 72


def test_training_outputs_contain_no_image_ids_or_patient_ids(tmp_path):
    metadata, images = make_dataset(tmp_path / "data")
    run_dir = run_training(small_config(tmp_path, metadata, images), log=lambda _: None)
    text = "".join(p.read_text() for p in run_dir.glob("*.json")) + (run_dir / "training_log.csv").read_text()
    assert "PAT_" not in text and ".png" not in text


def test_test_split_is_predicted_exactly_once_after_training(tmp_path, monkeypatch):
    metadata, images = make_dataset(tmp_path / "data")
    calls = []
    original = train_skin.predict

    def spy(model, dataset, device, batch_size):
        calls.append(len(dataset))
        return original(model, dataset, device, batch_size)

    monkeypatch.setattr(train_skin, "predict", spy)
    run_training(small_config(tmp_path, metadata, images, epochs=3), log=lambda _: None)
    assert len(calls) == 3 + 1  # validation once per epoch, then the test split once at the very end


def test_training_is_reproducible_on_cpu_for_a_fixed_seed(tmp_path):
    metadata, images = make_dataset(tmp_path / "data")
    runs = []
    for index in range(2):
        config = small_config(tmp_path / str(index), metadata, images, epochs=1)
        run_dir = run_training(config, log=lambda _: None)
        runs.append(json.loads((run_dir / "metrics.json").read_text())["test"]["confusion_matrix"]["matrix"])
    assert runs[0] == runs[1]


def test_cli_refuses_output_inside_the_image_folder(tmp_path, capsys):
    metadata, images = make_dataset(tmp_path / "data")
    code = train_skin.main(["--metadata", str(metadata), "--images", str(images), "--out-dir", str(images / "runs"), "--no-pretrained"])
    assert code == 2 and "must not be inside" in capsys.readouterr().err
    assert not (images / "runs").exists()


def test_cli_reports_data_problems_without_a_traceback(tmp_path, capsys):
    code = train_skin.main(["--metadata", str(tmp_path / "missing.csv"), "--images", str(tmp_path), "--out-dir", str(tmp_path / "out"), "--no-pretrained"])
    assert code == 2 and "ERROR" in capsys.readouterr().err
