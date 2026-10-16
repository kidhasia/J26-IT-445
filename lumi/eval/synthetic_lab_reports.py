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

    y = line_height // 2
    draw.text((_COLUMNS_X[0], y), SYNTHETIC_BANNER, font=font, fill="black")
    y += line_height
    draw.text((_COLUMNS_X[0], y), f"Report ID: {report_id}", font=font, fill="black")
    y += line_height * 2
    for x, heading in zip(_COLUMNS_X, ("Test", "Result", "Unit", "Reference Range")):
        draw.text((x, y), heading, font=font, fill="black")
    for row in rows:
        y += line_height
        for x, cell in zip(_COLUMNS_X, (row.test_name, row.value, row.unit, row.reference_range)):
            if cell:
                draw.text((x, y), cell, font=font, fill="black")

    buf = BytesIO()
    image.save(buf, format=image_format)
    ground_truth = {"report_id": report_id, "synthetic": True, "rows": [asdict(row) for row in rows]}
    return buf.getvalue(), ground_truth


def render_blank_image(size: tuple[int, int] = (800, 600)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, "white").save(buf, format="PNG")
    return buf.getvalue()
