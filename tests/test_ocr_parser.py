"""Pure parser tests: no OCR engine needed."""

import pytest

from lumi.pipelines.ocr.engine import OcrLine
from lumi.pipelines.ocr.parser import parse_lab_fields


def parse_one(text: str, confidence: float | None = 95.0):
    fields = parse_lab_fields([OcrLine(text, confidence)])
    assert len(fields) == 1, fields
    return fields[0]


def test_complete_row():
    field = parse_one("Haemoglobin 12.1 g/dL 11.5 - 15.5")
    assert (field.test_name, field.value, field.unit, field.reference_range) == ("Haemoglobin", "12.1", "g/dL", "11.5 - 15.5")
    assert field.missing_fields == []
    assert field.needs_review is False


def test_multi_word_name_and_upper_limit_range():
    field = parse_one("C-reactive protein 4 mg/L <5")
    assert (field.test_name, field.value, field.unit, field.reference_range) == ("C-reactive protein", "4", "mg/L", "< 5")


@pytest.mark.parametrize("printed", ["75-95", "75 -95", "75- 95", "75 – 95"])
def test_range_spacing_is_normalised_but_source_text_is_preserved(printed):
    text = f"Mean cell volume 82 fL {printed}"
    field = parse_one(text)
    assert field.reference_range == "75 - 95"
    assert field.source_text == text


def test_missing_range_is_reported():
    field = parse_one("Sodium 139 mmol/L")
    assert field.reference_range is None
    assert field.missing_fields == ["reference_range"]
    assert field.needs_review is True


def test_missing_unit_is_reported():
    field = parse_one("Platelet ratio 1.2 1.0 - 1.5")
    assert field.unit is None
    assert field.missing_fields == ["unit"]
    assert field.needs_review is True


def test_missing_value_is_reported_not_guessed():
    field = parse_one("Haemoglobin g/dL 11.5 - 15.5")
    assert field.value is None
    assert field.unit == "g/dL"
    assert field.missing_fields == ["value"]
    assert field.needs_review is True


def test_low_confidence_complete_row_needs_review():
    field = parse_one("Haemoglobin 12.1 g/dL 11.5 - 15.5", confidence=40.0)
    assert field.missing_fields == []
    assert field.needs_review is True


def test_unknown_confidence_needs_review():
    assert parse_one("Haemoglobin 12.1 g/dL 11.5 - 15.5", confidence=None).needs_review is True


def test_value_is_copied_as_printed_not_converted():
    field = parse_one("Glucose 05.10 mmol/L 3.9 - 5.8")
    assert field.value == "05.10"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "SYNTHETIC TEST REPORT - NOT REAL PATIENT DATA",
        "Test Result Unit Reference Range",
        "Report ID: SYN-0001",
        "Date: 16/10/2026",
        "Page 1 of 2",
        "12.1 g/dL",
    ],
)
def test_non_result_lines_are_skipped(text):
    assert parse_lab_fields([OcrLine(text, 95.0)]) == []


def test_line_numbers_point_to_the_source_line():
    lines = [OcrLine("Report ID: SYN-0001", 90.0), OcrLine("Test Result Unit", 90.0), OcrLine("Sodium 139 mmol/L 135 - 145", 90.0)]
    (field,) = parse_lab_fields(lines)
    assert field.line_number == 3
    assert field.source_text == "Sodium 139 mmol/L 135 - 145"
