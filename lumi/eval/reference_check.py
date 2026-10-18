"""Check that a synthetic report's reference text really matches its image, WITHOUT using any OCR.

Three independent checks, all of which must pass before a report is used for scoring:

1. The ground-truth file is well formed (marked synthetic, a report id, rows made only of text).
2. REGENERATION: drawing the report again from the ground truth gives exactly the stored image (same pixels). So the
   image was drawn from those rows and nothing else.
3. INK LAYOUT: looking only at the dark pixels of the stored image, the number of printed lines equals the number of
   reference lines, and in every printed table line the columns that should contain text contain ink and the columns
   that should be empty contain none. This does not depend on the drawing code or on OCR.

If any check fails, the report is NOT scored: a wrong reference would make the scores meaningless.
"""

import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

from lumi.eval.synthetic_lab_reports import _COLUMNS_X, SyntheticRow, layout_cells, reference_lines, render_lab_report

INK_THRESHOLD = 128  # a pixel darker than this (0 = black, 255 = white) counts as ink
MIN_GAP_BETWEEN_LINES = 4  # blank pixel rows needed to separate two printed lines
COLUMN_MARGIN = 8  # a cell can start slightly left of its column start without belonging to the previous column


@dataclass(frozen=True)
class Report:
    name: str
    image_path: Path
    image_bytes: bytes
    report_id: str
    rows: tuple[SyntheticRow, ...]

    @property
    def reference(self) -> list[str]:
        return reference_lines(self.rows, self.report_id)


class ReferenceError(Exception):
    """A report's ground truth is missing, malformed, or does not match its image."""


def load_report(image_path: Path) -> Report:
    json_path = image_path.with_suffix(".json")
    if not image_path.is_file():
        raise ReferenceError(f"{image_path.name}: image file is missing.")
    if not json_path.is_file():
        raise ReferenceError(f"{image_path.name}: ground-truth file {json_path.name} is missing.")
    try:
        truth = json.loads(json_path.read_text())
        rows = tuple(SyntheticRow(**{key: str(row[key]) for key in ("test_name", "value", "unit", "reference_range")}) for row in truth["rows"])
        report_id = str(truth["report_id"])
        synthetic = truth["synthetic"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ReferenceError(f"{json_path.name}: ground truth is not in the expected format.") from exc
    if synthetic is not True:
        raise ReferenceError(f"{json_path.name}: not marked as synthetic data; refusing to use it.")
    if not rows or not report_id:
        raise ReferenceError(f"{json_path.name}: no rows or no report id.")
    return Report(image_path.stem, image_path, image_path.read_bytes(), report_id, rows)


def _pixels(image_bytes: bytes) -> np.ndarray:
    with Image.open(BytesIO(image_bytes)) as image:
        return np.asarray(image.convert("L"))


def _bands(ink: np.ndarray) -> list[tuple[int, int]]:
    """Printed lines as (first row, last row) bands of ink, merging bands closer than MIN_GAP_BETWEEN_LINES."""
    has_ink = ink.any(axis=1)
    bands: list[list[int]] = []
    for row, present in enumerate(has_ink):
        if not present:
            continue
        if bands and row - bands[-1][1] <= MIN_GAP_BETWEEN_LINES:
            bands[-1][1] = row
        else:
            bands.append([row, row])
    return [(a, b) for a, b in bands]


def verify_report(report: Report) -> list[str]:
    """Return a list of problems; an empty list means the reference matches the image."""
    problems: list[str] = []
    expected_cells = layout_cells(report.rows, report.report_id)
    expected_lines = report.reference

    # check 2: regeneration gives the same picture
    regenerated, _ = render_lab_report(report.rows, report.report_id)
    stored, again = _pixels(report.image_bytes), _pixels(regenerated)
    if stored.shape != again.shape or not np.array_equal(stored, again):
        problems.append("the image is not what the ground truth draws (regenerating it gives different pixels)")

    # check 3: independent look at the ink
    ink = stored < INK_THRESHOLD
    bands = _bands(ink)
    if len(bands) != len(expected_lines):
        problems.append(f"the image has {len(bands)} printed lines but the reference has {len(expected_lines)}")
        return problems
    edges = [x - COLUMN_MARGIN for x in _COLUMNS_X] + [ink.shape[1]]
    occupied = {(cell.line, cell.column) for cell in expected_cells}
    for line_number, (top, bottom) in enumerate(bands):
        if line_number < 2:  # banner and report id are wide text that crosses several columns
            continue
        for column in range(len(_COLUMNS_X)):
            has_ink = bool(ink[top : bottom + 1, edges[column] : edges[column + 1]].any())
            should_have = (line_number, column) in occupied
            if has_ink != should_have:
                problems.append(f"line {line_number + 1}, column {column + 1}: " + ("expected text but the image is blank there" if should_have else "expected a blank cell but the image has ink there"))
    return problems
