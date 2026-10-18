"""How uncertain are the held-out test numbers? Patient-level bootstrap confidence intervals.

Resamples whole PATIENTS (with replacement) from the test split 2,000 times and recomputes the metrics, so
patients with several photos are not treated as independent. This describes uncertainty only; it does not change
or tune the model. Prints aggregates only.

Usage:  .venv/bin/python scripts/bootstrap_test_ci.py RUN_DIR METADATA_CSV IMAGES_DIR
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from lumi.ml.offline import offline_probabilities  # noqa: E402
from lumi.ml.skin_data import CLASSES, load_samples, make_splits, resolve_duplicates  # noqa: E402
from lumi.ml.train_skin import compute_metrics  # noqa: E402

ROUNDS = 2000


def main(run_dir: Path, metadata: Path, images: Path) -> int:
    config = json.loads((run_dir / "config.json").read_text())["training_config"]
    samples, _ = resolve_duplicates(load_samples(metadata, images))
    split = make_splits(samples, config["seed"], config["n_folds"], config["test_fold"], config["val_fold"])
    indices = [i for i, s in enumerate(samples) if split[s.img_id] == "test"]
    probabilities = offline_probabilities(run_dir, samples, indices)
    truth = np.array([CLASSES.index(samples[i].label) for i in indices])
    predicted = probabilities.argmax(1)
    point = compute_metrics(truth, predicted, probabilities)

    rows_by_patient: dict[str, list[int]] = defaultdict(list)
    for row, i in enumerate(indices):
        rows_by_patient[samples[i].patient_id].append(row)
    patients = list(rows_by_patient.values())
    rng = np.random.default_rng(0)
    accuracy, macro_f1, recalls = [], [], {c: [] for c in CLASSES}
    for _ in range(ROUNDS):
        chosen = np.concatenate([patients[j] for j in rng.integers(0, len(patients), len(patients))])
        metrics = compute_metrics(truth[chosen], predicted[chosen], None)
        accuracy.append(metrics["accuracy"])
        macro_f1.append(metrics["macro_f1"])
        for name in CLASSES:
            if metrics["per_class"][name]["support"] > 0:
                recalls[name].append(metrics["per_class"][name]["recall"])

    def interval(values):
        low, high = np.percentile(values, [2.5, 97.5])
        return f"{low:.3f} to {high:.3f}"

    print(f"Test images {len(indices)} from {len(patients)} patients; {ROUNDS} patient-level resamples (seed 0)")
    print(f"accuracy  {point['accuracy']:.3f}   95% interval {interval(accuracy)}")
    print(f"macro-F1  {point['macro_f1']:.3f}   95% interval {interval(macro_f1)}")
    for name in CLASSES:
        support = point["per_class"][name]["support"]
        print(f"recall {name} {point['per_class'][name]['recall']:.3f}   95% interval {interval(recalls[name])}   (n={support})")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])))
