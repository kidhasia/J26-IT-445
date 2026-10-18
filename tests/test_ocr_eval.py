"""The OCR evaluation harness: reference text checked against images, scoring with systems whose answers are known,
aggregation, and the real run with Tesseract. Everything uses the project's own synthetic reports."""

import hashlib
import json
import shutil
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from lumi.eval import ocr_eval
from lumi.eval import text_metrics as tm
from lumi.eval.ocr_eval import SystemOutput, evaluate, find_reports, score_fields, score_text
from lumi.eval.reference_check import ReferenceError, Report, load_report, verify_report
from lumi.eval.synthetic_lab_reports import (
    COLUMN_HEADINGS,
    DEFAULT_ROWS,
    SYNTHETIC_BANNER,
    SyntheticRow,
    layout_cells,
    reference_lines,
    render_lab_report,
)

requires_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")

ROW_SETS = {
    "complete": DEFAULT_ROWS,
    "missing_value": (SyntheticRow("Haemoglobin", "", "g/dL", "11.5 - 15.5"), *DEFAULT_ROWS[1:3]),
    "missing_range": (SyntheticRow("Sodium", "139", "mmol/L", ""), *DEFAULT_ROWS[4:]),
}


def write_report(folder: Path, name: str, rows, report_id: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    image, truth = render_lab_report(rows, report_id=report_id)
    (folder / f"{name}.png").write_bytes(image)
    (folder / f"{name}.json").write_text(json.dumps(truth, indent=2))
    return folder / f"{name}.png"


@pytest.fixture
def reports_folder(tmp_path) -> Path:
    for index, (name, rows) in enumerate(ROW_SETS.items(), start=1):
        write_report(tmp_path / "reports", f"syn_{index:04d}_{name}", rows, f"SYN-{index:04d}")
    return tmp_path / "reports"


@pytest.fixture
def reports(reports_folder) -> list[Report]:
    return find_reports(reports_folder)


# ---------------------------------------------------------------- the generator was refactored: it must not have changed


def legacy_render(rows, report_id, font_size=28) -> bytes:
    """The ORIGINAL drawing code from before the reference text was derived from a shared list. It is the oracle that
    proves the refactor left every image identical."""
    font = ImageFont.load_default(size=font_size)
    line_height = int(font_size * 2)
    image = Image.new("RGB", (1240, line_height * (len(rows) + 6)), "white")
    draw = ImageDraw.Draw(image)
    columns = (60, 480, 640, 820)
    y = line_height // 2
    draw.text((columns[0], y), SYNTHETIC_BANNER, font=font, fill="black")
    y += line_height
    draw.text((columns[0], y), f"Report ID: {report_id}", font=font, fill="black")
    y += line_height * 2
    for x, heading in zip(columns, COLUMN_HEADINGS):
        draw.text((x, y), heading, font=font, fill="black")
    for row in rows:
        y += line_height
        for x, cell in zip(columns, (row.test_name, row.value, row.unit, row.reference_range)):
            if cell:
                draw.text((x, y), cell, font=font, fill="black")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize("name", list(ROW_SETS))
def test_refactored_generator_draws_exactly_the_same_image_as_the_original(name):
    new, _ = render_lab_report(ROW_SETS[name], report_id="SYN-9999")
    assert new == legacy_render(ROW_SETS[name], "SYN-9999")


def test_generating_a_report_twice_gives_identical_bytes():
    assert render_lab_report()[0] == render_lab_report()[0]


# ---------------------------------------------------------------- reference text


def test_reference_lines_are_what_is_printed_in_reading_order():
    lines = reference_lines(ROW_SETS["missing_value"], "SYN-0002")
    assert lines == [
        "SYNTHETIC TEST REPORT - NOT REAL PATIENT DATA",
        "Report ID: SYN-0002",
        "Test Result Unit Reference Range",
        "Haemoglobin g/dL 11.5 - 15.5",  # the empty result cell is simply not printed, so it is not in the reference
        "Haematocrit 36.5 % 34 - 45",
        "Mean cell volume 82 fL 75 - 95",
    ]


def test_reference_comes_from_the_same_list_that_draws_the_image():
    for rows in ROW_SETS.values():
        cells = layout_cells(rows, "SYN-0007")
        assert all(cell.text for cell in cells)  # empty cells are never drawn, so they are never in the reference
        assert " ".join(reference_lines(rows, "SYN-0007")).split() == " ".join(c.text for c in sorted(cells, key=lambda c: (c.line, c.column))).split()
        assert len(reference_lines(rows, "SYN-0007")) == 3 + len(rows)


# ---------------------------------------------------------------- the reference is checked against the image before scoring


def test_genuine_reports_pass_verification(reports):
    assert len(reports) == 3
    for report in reports:
        assert verify_report(report) == [], report.name


def tamper_json(path: Path, change) -> Report:
    truth = json.loads(path.with_suffix(".json").read_text())
    change(truth)
    path.with_suffix(".json").write_text(json.dumps(truth))
    return load_report(path)


def test_a_wrong_value_in_the_ground_truth_is_caught(reports_folder):
    image = next(reports_folder.glob("*complete.png"))
    report = tamper_json(image, lambda t: t["rows"][0].update(value="99.9"))
    assert any("not what the ground truth draws" in p for p in verify_report(report))


def test_a_wrong_report_id_in_the_ground_truth_is_caught(reports_folder):
    image = next(reports_folder.glob("*complete.png"))
    assert verify_report(tamper_json(image, lambda t: t.update(report_id="SYN-0042")))


def test_an_extra_or_missing_row_is_caught_by_counting_printed_lines(reports_folder):
    image = next(reports_folder.glob("*complete.png"))
    extra = tamper_json(image, lambda t: t["rows"].append(dict(test_name="X", value="1", unit="u", reference_range="1 - 2")))
    assert any("printed lines" in p for p in verify_report(extra))
    image2 = next(reports_folder.glob("*missing_value.png"))
    fewer = tamper_json(image2, lambda t: t["rows"].pop())
    assert any("printed lines" in p for p in verify_report(fewer))


def test_ink_check_catches_blank_cells_claimed_as_text_and_the_reverse(reports_folder):
    image = next(reports_folder.glob("*complete.png"))
    claimed_blank = tamper_json(image, lambda t: t["rows"][1].update(unit=""))
    assert any("expected a blank cell but the image has ink" in p for p in verify_report(claimed_blank))
    pixels = np.array(Image.open(image).convert("RGB"))
    pixels[250:290, 480:600] = 255  # erase a printed value from the picture itself
    Image.fromarray(pixels).save(image)
    erased = load_report(image)
    erased = Report(erased.name, erased.image_path, image.read_bytes(), erased.report_id, erased.rows)
    assert any("expected text but the image is blank" in p for p in verify_report(erased))


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda p: p.with_suffix(".json").unlink(), "ground-truth file"),
        (lambda p: p.with_suffix(".json").write_text("{not json"), "not in the expected format"),
        (lambda p: p.with_suffix(".json").write_text(json.dumps({"report_id": "X", "synthetic": True})), "not in the expected format"),
        (lambda p: p.with_suffix(".json").write_text(json.dumps({"report_id": "X", "synthetic": False, "rows": []})), "not marked as synthetic"),
        (lambda p: p.with_suffix(".json").write_text(json.dumps({"report_id": "X", "synthetic": True, "rows": []})), "no rows"),
    ],
)
def test_unusable_ground_truth_is_refused(reports_folder, change, message):
    image = next(reports_folder.glob("*complete.png"))
    change(image)
    with pytest.raises(ReferenceError, match=message):
        load_report(image)


def test_missing_image_or_folder_is_refused(tmp_path):
    with pytest.raises(ReferenceError, match="image file is missing"):
        load_report(tmp_path / "nothing.png")
    with pytest.raises(ReferenceError, match="does not exist"):
        find_reports(tmp_path / "no_such_folder")
    (tmp_path / "empty").mkdir()
    with pytest.raises(ReferenceError, match="No .png reports"):
        find_reports(tmp_path / "empty")


# ---------------------------------------------------------------- scoring with systems whose answers are known


def perfect(report: Report) -> SystemOutput:
    text = "\n".join(report.reference)
    return SystemOutput(text=text, lines=report.reference, fields=expected_fields(report))


def expected_fields(report: Report) -> list[dict]:
    return [
        {"test_name": r.test_name, "value": r.value or None, "unit": r.unit or None, "reference_range": r.reference_range or None,
         "needs_review": False, "source_text": " ".join(x for x in (r.test_name, r.value, r.unit, r.reference_range) if x), "line_number": 4 + i}
        for i, r in enumerate(report.rows)
    ]


def nothing(report: Report) -> SystemOutput:
    return SystemOutput(text="", lines=[], fields=[])


def one_character_wrong(report: Report) -> SystemOutput:
    text = "\n".join(report.reference)
    return SystemOutput(text="X" + text[1:], lines=text.splitlines(), fields=expected_fields(report))


def test_a_perfect_system_scores_zero_error(reports):
    result = evaluate(reports, {"perfect": perfect})["perfect"]
    aggregate = result["aggregate"]
    for level in ("cer_whitespace_normalised", "cer_line_aware", "cer_raw", "wer"):
        assert aggregate[level]["error_rate"] == 0.0 and aggregate[level]["edit_distance"] == 0
    assert aggregate["lines_reproduced_exactly"] == {"reproduced": 21, "reference_lines": 21}  # 9 + 6 + 6 printed lines in the three reports
    assert result["field_level"]["field_exact_accuracy"] == 1.0 and result["field_level"]["row_recall"] == 1.0


def test_a_system_that_reads_nothing_has_total_error(reports):
    aggregate = evaluate(reports, {"nothing": nothing})["nothing"]["aggregate"]
    assert aggregate["cer_whitespace_normalised"]["error_rate"] == 1.0 and aggregate["wer"]["error_rate"] == 1.0
    assert aggregate["cer_whitespace_normalised"]["substitutions"] == 0 and aggregate["cer_whitespace_normalised"]["insertions"] == 0
    assert aggregate["lines_reproduced_exactly"]["reproduced"] == 0
    assert aggregate["word_error_categories"]["missing_word"] + aggregate["word_error_categories"]["missing_number"] == aggregate["wer"]["reference_length"]


def test_micro_and_macro_averages_are_calculated_as_documented(reports):
    result = evaluate(reports, {"one_wrong": one_character_wrong})["one_wrong"]
    lengths = [len(tm.whitespace_normalised("\n".join(r.reference))) for r in sorted(reports, key=lambda r: r.name)]
    cer = result["aggregate"]["cer_whitespace_normalised"]
    assert cer["substitutions"] == 3 and cer["edit_distance"] == 3  # one wrong character in each of the three reports
    assert cer["reference_length"] == sum(lengths)
    assert cer["error_rate"] == pytest.approx(3 / sum(lengths), abs=1e-6)  # micro: total errors over total length
    assert cer["macro_average_rate"] == pytest.approx(sum(1 / n for n in lengths) / 3, abs=1e-6)  # macro: mean of per-report rates
    assert cer["error_rate"] != cer["macro_average_rate"]  # the reports have different lengths, so the two differ
    per_report = [r["scores"]["cer_whitespace_normalised"] for r in result["per_report"]]
    assert [p["edit_distance"] for p in per_report] == [1, 1, 1] and [p["reference_length"] for p in per_report] == lengths


def test_every_system_is_scored_against_exactly_the_same_reference(reports):
    results = evaluate(reports, {"a": perfect, "b": nothing, "c": one_character_wrong})
    for index, report in enumerate(sorted(reports, key=lambda r: r.name)):
        hashes = {name: results[name]["per_report"][index]["reference_sha256"] for name in results}
        assert len(set(hashes.values())) == 1, hashes
        assert next(iter(hashes.values())) == hashlib.sha256("\n".join(report.reference).encode()).hexdigest()
    lengths = {name: results[name]["aggregate"]["cer_whitespace_normalised"]["reference_length"] for name in results}
    assert len(set(lengths.values())) == 1


def test_text_from_the_wrong_report_is_scored_as_wrong_not_accepted(reports):
    by_name = sorted(reports, key=lambda r: r.name)
    other_text = {by_name[0].name: "\n".join(by_name[1].reference), by_name[1].name: "\n".join(by_name[0].reference), by_name[2].name: "\n".join(by_name[2].reference)}

    def mismatched(report: Report) -> SystemOutput:
        return SystemOutput(text=other_text[report.name], lines=[], fields=[])

    per_report = evaluate(reports, {"mismatched": mismatched})["mismatched"]["per_report"]
    assert per_report[0]["scores"]["wer"]["error_rate"] > 0 and per_report[1]["scores"]["wer"]["error_rate"] > 0
    assert per_report[2]["scores"]["wer"]["error_rate"] == 0.0


def test_text_levels_differ_only_in_how_white_space_is_treated():
    reference = ["Hb 12.1 g/dL", "Na 139 mmol/L"]
    messy = "Hb  12.1 g/dL\n\n\nNa 139   mmol/L\n\x0c"
    counts = score_text(reference, messy)["counts"]
    assert counts["cer_whitespace_normalised"].distance == 0 and counts["cer_line_aware"].distance == 0 and counts["wer"].distance == 0
    assert counts["cer_raw"].distance > 0  # the raw level counts the extra blank lines and the form feed
    joined = score_text(reference, "Hb 12.1 g/dL Na 139 mmol/L")["counts"]
    assert joined["cer_whitespace_normalised"].distance == 0 and joined["cer_line_aware"].distance == 1  # a missing line break


def test_no_reports_or_duplicate_names_are_refused(reports):
    with pytest.raises(ReferenceError):
        evaluate([], {"perfect": perfect})
    with pytest.raises(ReferenceError, match="same name"):
        evaluate([reports[0], reports[0]], {"perfect": perfect})


def test_scoring_does_not_change_the_reference_or_the_report(reports):
    before = [(r.name, list(r.reference), r.image_bytes) for r in reports]
    evaluate(reports, {"a": perfect, "b": nothing})
    assert before == [(r.name, list(r.reference), r.image_bytes) for r in reports]


# ---------------------------------------------------------------- field-level scoring


def test_field_scoring_finds_wrong_missing_and_silent_errors(reports):
    report = next(r for r in reports if "missing_value" in r.name)
    parsed = expected_fields(report)
    assert score_fields(report, parsed)["fields_exactly_correct"] == {"value": 3, "unit": 3, "reference_range": 3}
    assert score_fields(report, parsed)["wrong_or_missing"] == []  # the blank value is expected as null and was parsed as null

    parsed[1]["value"] = "36.9"  # a wrong value that the pipeline did not flag
    parsed[2]["needs_review"] = True  # a flag on a row that is actually right
    parsed.pop(0)  # a row that was not found at all
    parsed.append({**parsed[0], "test_name": "Invented row"})
    scored = score_fields(report, parsed)
    assert scored["rows_matched_by_name"] == 2 and scored["spurious_rows"] == ["Invented row"]
    assert scored["rows_with_a_wrong_field_that_were_not_flagged_for_review"] == 1
    assert scored["rows_flagged_for_review_although_every_field_was_correct"] == 1
    assert {"row": "Haemoglobin", "problem": "row not found"} in scored["wrong_or_missing"]


def test_a_blank_cell_that_was_read_as_a_value_is_an_error(reports):
    report = next(r for r in reports if "missing_value" in r.name)
    parsed = expected_fields(report)
    parsed[0]["value"] = "12.1"  # a value invented for a cell that is blank on the page
    assert {"row": "Haemoglobin", "field": "value", "expected": None, "got": "12.1"} in score_fields(report, parsed)["wrong_or_missing"]


def test_spacing_normalisation_is_reported_when_it_is_what_made_a_range_correct(reports):
    report = next(r for r in reports if "complete" in r.name)
    parsed = expected_fields(report)
    parsed[2]["source_text"] = "Mean cell volume 82 fL 75-95"  # as the OCR read it; the pipeline reported "75 - 95"
    helped = score_fields(report, parsed)["reference_ranges_correct_only_after_pipeline_spacing_normalisation"]
    assert helped == [{"as_read": "Mean cell volume 82 fL 75-95", "reported_as": "75 - 95"}]


# ---------------------------------------------------------------- the real run with Tesseract


@requires_tesseract
def test_real_run_produces_results_for_both_systems_on_verified_reports(reports_folder):
    results = ocr_eval.run(reports_folder)
    assert set(results["systems"]) == {"lumi_pipeline", "plain_tesseract"}
    assert set(results["reference_verification"].values()) == {"verified"}
    assert results["dataset"]["reports"] == 3 and results["dataset"]["distinct_table_rows"] <= results["dataset"]["table_rows_total"]
    for system in results["systems"].values():
        aggregate = system["aggregate"]
        assert aggregate["reports"] == 3 and len(system["per_report"]) == 3
        assert 0.0 <= aggregate["cer_whitespace_normalised"]["error_rate"] < 0.10  # a smoke bound for clean synthetic text, not a target
        assert aggregate["wer"]["reference_length"] == results["dataset"]["reference_words_total"]
    json.dumps(results)  # everything is JSON-serialisable


@requires_tesseract
def test_the_lumi_system_is_the_real_pipeline_output(reports):
    from lumi.pipelines.ocr.engine import TesseractEngine
    from lumi.pipelines.ocr.pipeline import LabReportOcrPipeline
    from lumi.validation import ValidatedFile

    report = reports[0]
    direct = LabReportOcrPipeline(TesseractEngine()).run(ValidatedFile(report.image_bytes, "image/png", "x"), None).result
    assert ocr_eval.run_lumi_pipeline(report).text == direct["extracted_text"]
    assert ocr_eval.run_lumi_pipeline(report).fields == direct["fields"]


@requires_tesseract
def test_command_line_run_writes_a_reproducible_results_file(reports_folder, tmp_path, capsys):
    outputs = []
    for run in ("first", "second"):
        out = tmp_path / f"{run}.json"
        assert ocr_eval.main(["--reports", str(reports_folder), "--out", str(out)]) == 0
        outputs.append(out.read_bytes())
    assert hashlib.sha256(outputs[0]).hexdigest() == hashlib.sha256(outputs[1]).hexdigest()  # identical, byte for byte
    text = outputs[0].decode()
    assert "generated_at" not in text and "timestamp" not in text
    shown = capsys.readouterr().out
    assert "Reports evaluated: 3" in shown and "Reference text verified against every image: yes" in shown


@requires_tesseract
def test_command_line_refuses_to_score_when_a_reference_does_not_match_its_image(reports_folder, tmp_path, capsys):
    image = next(reports_folder.glob("*complete.png"))
    tamper_json(image, lambda t: t["rows"][0].update(value="99.9"))
    out = tmp_path / "never_written.json"
    assert ocr_eval.main(["--reports", str(reports_folder), "--out", str(out)]) == 2
    assert not out.exists() and "nothing was scored" in capsys.readouterr().err


def test_command_line_explains_a_missing_folder(tmp_path, capsys):
    assert ocr_eval.main(["--reports", str(tmp_path / "nope"), "--no-write"]) == 2
    assert "make_synthetic_lab_reports.py" in capsys.readouterr().err


@requires_tesseract
def test_no_write_flag_prints_but_creates_no_file(reports_folder, tmp_path):
    out = tmp_path / "should_not_exist.json"
    assert ocr_eval.main(["--reports", str(reports_folder), "--out", str(out), "--no-write"]) == 0
    assert not out.exists()
