"""Find lab-result rows in OCR text lines.

A row looks like:  <test name>  <result>  <unit>  <reference range>
for example:       Haemoglobin  12.1      g/dL    11.5 - 15.5

This is simple pattern matching, not medical interpretation:
- values and units are copied as printed, never converted or corrected;
- reference ranges are copied as printed, because they depend on the laboratory and
  the patient's age, so the parser never decides whether a result is normal;
- anything missing or read with low OCR confidence is flagged with needs_review.
"""

import re
from dataclasses import asdict, dataclass

from lumi.pipelines.ocr.engine import OcrLine

# An engineering threshold for flagging uncertain OCR, not a clinical measure.
DEFAULT_REVIEW_CONFIDENCE = 60.0

_NUMBER = r"\d+(?:\.\d+)?"
_RANGE_AT_END = re.compile(
    rf"(?:(?P<low>{_NUMBER})\s*[-–]\s*(?P<high>{_NUMBER})|(?P<op>[<>≤≥])\s*(?P<limit>{_NUMBER}))\s*$"
)
_VALUE = re.compile(rf"^[<>]?{_NUMBER}$")
_UNIT_LIKE = re.compile(r"[/%]")
_PAGE_MARKER = re.compile(rf"^page\s+{_NUMBER}(?:\s+of\s+{_NUMBER})?$", re.IGNORECASE)


@dataclass(frozen=True)
class LabField:
    test_name: str
    value: str | None
    unit: str | None
    reference_range: str | None
    missing_fields: list[str]
    needs_review: bool
    line_number: int  # 1-based position in the extracted text, so a reader can find the source
    source_text: str  # the exact OCR line this field was parsed from
    ocr_confidence: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def parse_lab_fields(lines: list[OcrLine], review_confidence: float = DEFAULT_REVIEW_CONFIDENCE) -> list[LabField]:
    fields = []
    for line_number, line in enumerate(lines, start=1):
        field = _parse_line(line, line_number, review_confidence)
        if field is not None:
            fields.append(field)
    return fields


def _parse_line(line: OcrLine, line_number: int, review_confidence: float) -> LabField | None:
    text = line.text.strip()
    if not any(ch.isdigit() for ch in text) or _PAGE_MARKER.match(text):
        return None  # headers, labels and "Page 1 of 2" footers are not result rows

    reference_range = None
    match = _RANGE_AT_END.search(text)
    if match:
        if match["low"]:
            reference_range = f"{match['low']} - {match['high']}"
        else:
            reference_range = f"{match['op']} {match['limit']}"
        text = text[: match.start()].strip()

    tokens = text.split()
    value_index = next((i for i, token in enumerate(tokens) if _VALUE.match(token)), None)
    if value_index is not None:
        name_tokens, value = tokens[:value_index], tokens[value_index]
        unit = " ".join(tokens[value_index + 1 :]) or None
    else:
        value = None
        name_tokens = tokens
        unit = None
        if name_tokens and _UNIT_LIKE.search(name_tokens[-1]):
            unit = name_tokens.pop()

    test_name = " ".join(name_tokens)
    # Skip lines that are not result rows: no test name, "Label: value" lines (IDs, dates),
    # or lines with neither a value nor a range.
    if not test_name or not any(ch.isalpha() for ch in test_name) or test_name.endswith(":"):
        return None
    if value is None and reference_range is None:
        return None

    missing = [name for name, present in (("value", value), ("unit", unit), ("reference_range", reference_range)) if not present]
    low_confidence = line.confidence is None or line.confidence < review_confidence
    return LabField(
        test_name=test_name,
        value=value,
        unit=unit,
        reference_range=reference_range,
        missing_fields=missing,
        needs_review=bool(missing) or low_confidence,
        line_number=line_number,
        source_text=line.text,
        ocr_confidence=line.confidence,
    )
