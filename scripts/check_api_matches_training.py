"""Deployment check: do the API's predictions match the offline test evaluation of a trained run?

It rebuilds the same patient-level split (same seed and folds, read from the run's config.json), sends every
held-out TEST image through the real API code with the real checkpoint, and compares the API's macro-F1 with the
number saved by training. This does not tune anything; it only checks that serving matches training.
It prints aggregates only: no ids, file names or per-image results.

Usage:  .venv/bin/python scripts/check_api_matches_training.py RUN_DIR METADATA_CSV IMAGES_DIR
"""

import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lumi.auth import parse_api_keys  # noqa: E402
from lumi.config import Settings  # noqa: E402
from lumi.main import create_app  # noqa: E402
from lumi.ml.skin_data import CLASSES, load_samples, make_splits, resolve_duplicates  # noqa: E402
from lumi.ml.train_skin import compute_metrics  # noqa: E402


def main(run_dir: Path, metadata: Path, images: Path) -> int:
    config = json.loads((run_dir / "config.json").read_text())["training_config"]
    saved = json.loads((run_dir / "metrics.json").read_text())["test"]
    samples, _ = resolve_duplicates(load_samples(metadata, images))
    split = make_splits(samples, config["seed"], config["n_folds"], config["test_fold"], config["val_fold"])
    test = [s for s in samples if split[s.img_id] == "test"]

    key = "check-api-key-0123456789"
    settings = Settings(api_key_hashes=parse_api_keys(f"check:{key}"), rate_limit_per_minute=100_000,
                        skin_model_path=str(run_dir / "checkpoint.pt"), max_upload_bytes=10 * 1024 * 1024)
    client = TestClient(create_app(settings), headers={"Authorization": f"Bearer {key}"})

    true, predicted, probabilities, rejected = [], [], [], {}
    for sample in test:
        response = client.post("/api/v1/analyze", data={"input_type": "skin_image"},
                               files={"file": ("image.png", sample.path.read_bytes(), "image/png")})
        if response.status_code != 200:
            code = response.json()["error"]["code"]
            rejected[f"{response.status_code} {code}"] = rejected.get(f"{response.status_code} {code}", 0) + 1
            continue
        by_class = {p["class"]: p["probability"] for p in response.json()["result"]["probabilities"]}
        row = [by_class[c] for c in CLASSES]
        true.append(CLASSES.index(sample.label))
        predicted.append(int(np.argmax(row)))
        probabilities.append(row)

    print(f"Test images: {len(test)} | served by the API: {len(true)} | rejected by the API: {rejected or 0}")
    if not true:
        return 1
    api = compute_metrics(np.array(true), np.array(predicted), np.array(probabilities))
    print(f"Macro-F1  API {api['macro_f1']:.4f}  vs  saved by training {saved['macro_f1']:.4f}")
    print(f"Accuracy  API {api['accuracy']:.4f}  vs  saved by training {saved['accuracy']:.4f}")
    match = len(true) == len(test) and abs(api["macro_f1"] - saved["macro_f1"]) < 0.01
    print("RESULT:", "API matches the offline evaluation" if match else "DIFFERENCE FOUND, investigate before trusting the endpoint")
    return 0 if match else 1


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])))
