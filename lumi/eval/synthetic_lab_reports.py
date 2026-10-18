"""Synthetic laboratory report images for testing the OCR pipeline.

Everything here is made up for software testing. The values and reference ranges are
placeholders chosen to look like a printed report; they are NOT clinical reference values,
and no patient is described. Each image is stamped as synthetic.

render_lab_report() returns the image bytes together with the ground truth (the exact
rows that were drawn), which can later be used to measure OCR error rates.
"""

from dataclasses import asdict, dataclass
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

SYNTHETIC_BANNER = "SYNTHETIC TEST REPORT - NOT REAL PATIENT DATA"


@dataclass(frozen=True)
class SyntheticRow:
    test_name: str
    value: str  # "" draws an empty cell, to simulate a missing value
    unit: str
    reference_range: str


DEFAULT_ROWS: tuple[SyntheticRow, ...] = (
    SyntheticRow("Haemoglobin", "12.1", "g/dL", "11.5 - 15.5"),
    SyntheticRow("Haematocrit", "36.5", "%", "34 - 45"),
    SyntheticRow("Mean cell volume", "82", "fL", "75 - 95"),
    SyntheticRow("Sodium", "139", "mmol/L", "135 - 145"),
    SyntheticRow("Glucose", "5.1", "mmol/L", "3.9 - 5.8"),
    SyntheticRow("C-reactive protein", "4", "mg/L", "< 5"),
)

_COLUMNS_X = (60, 480, 640, 820)  # test name, result, unit, reference range


COLUMN_HEADINGS = ("Test", "Result", "Unit", "Reference Range")


@dataclass(frozen=True)
class DrawnCell:
    """One piece of text exactly as it is drawn: what, where, and which line and column of the report it is in."""

    text: str
    x: int
    y: int
    line: int  # 0 = banner, 1 = report id, 2 = column headings, 3 and up = table rows
    column: int


def layout_cells(rows: tuple[SyntheticRow, ...], report_id: str, font_size: int = 28) -> list[DrawnCell]:
    """Every piece of text on the report, in the order and at the positions it is drawn. Empty cells are not drawn,
    so they are not in this list. This single list drives both the drawing and the reference text."""
    line_height = int(font_size * 2)
    y = line_height // 2
    cells = [DrawnCell(SYNTHETIC_BANNER, _COLUMNS_X[0], y, 0, 0)]
    y += line_height
    cells.append(DrawnCell(f"Report ID: {report_id}", _COLUMNS_X[0], y, 1, 0))
    y += line_height * 2
    cells += [DrawnCell(heading, x, y, 2, column) for column, (x, heading) in enumerate(zip(_COLUMNS_X, COLUMN_HEADINGS))]
    for number, row in enumerate(rows):
        y += line_height
        values = (row.test_name, row.value, row.unit, row.reference_range)
        cells += [DrawnCell(text, x, y, 3 + number, column) for column, (x, text) in enumerate(zip(_COLUMNS_X, values)) if text]
    return cells


def reference_lines(rows: tuple[SyntheticRow, ...], report_id: str) -> list[str]:
    """The text printed on the report as a person reads it: one string per printed line, columns left to right
    joined by a single space. This is the reference ("correct answer") used to score OCR."""
    by_line: dict[int, list[DrawnCell]] = {}
    for cell in layout_cells(rows, report_id):
        by_line.setdefault(cell.line, []).append(cell)
    return [" ".join(cell.text for cell in sorted(cells, key=lambda c: c.column)) for _, cells in sorted(by_line.items())]


def render_lab_report(
    rows: tuple[SyntheticRow, ...] = DEFAULT_ROWS,
    report_id: str = "SYN-0001",
    image_format: str = "PNG",
    font_size: int = 28,
) -> tuple[bytes, dict]:
    font = ImageFont.load_default(size=font_size)
    line_height = int(font_size * 2)
    height = line_height * (len(rows) + 6)
    image = Image.new("RGB", (1240, height), "white")
    draw = ImageDraw.Draw(image)
    for cell in layout_cells(rows, report_id, font_size):
        draw.text((cell.x, cell.y), cell.text, font=font, fill="black")

    buf = BytesIO()
    image.save(buf, format=image_format)
    ground_truth = {"report_id": report_id, "synthetic": True, "rows": [asdict(row) for row in rows]}
    return buf.getvalue(), ground_truth


def render_blank_image(size: tuple[int, int] = (800, 600)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, "white").save(buf, format="PNG")
    return buf.getvalue()
