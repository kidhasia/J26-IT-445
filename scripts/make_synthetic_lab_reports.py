"""Save sample synthetic lab report images (+ ground-truth JSON) for manual testing.

Usage:  .venv/bin/python scripts/make_synthetic_lab_reports.py
Output: data/synthetic/lab_reports/
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lumi.eval.synthetic_lab_reports import DEFAULT_ROWS, SyntheticRow, render_lab_report  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "lab_reports"

SAMPLES = {
    "syn_0001_complete": DEFAULT_ROWS,
    "syn_0002_missing_value": (SyntheticRow("Haemoglobin", "", "g/dL", "11.5 - 15.5"), *DEFAULT_ROWS[1:3]),
    "syn_0003_missing_range": (SyntheticRow("Sodium", "139", "mmol/L", ""), *DEFAULT_ROWS[4:]),
}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for index, (name, rows) in enumerate(SAMPLES.items(), start=1):
        image, truth = render_lab_report(rows, report_id=f"SYN-{index:04d}")
        (OUTPUT_DIR / f"{name}.png").write_bytes(image)
        (OUTPUT_DIR / f"{name}.json").write_text(json.dumps(truth, indent=2))
        print(f"wrote {OUTPUT_DIR / name}.png (+ .json ground truth)")


if __name__ == "__main__":
    main()
