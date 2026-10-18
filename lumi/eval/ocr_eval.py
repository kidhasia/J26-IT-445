"""Measure lab-report OCR accuracy: the LUMI pipeline against plain Tesseract, on the synthetic reports.

Run:  .venv/bin/python -m lumi.eval.ocr_eval            (writes docs/evaluations/ocr_synthetic_results.json)

Rules this script follows:
- Only the synthetic reports (images + ground truth) in --reports are used, and only after their reference text has been
  verified against the image (lumi.eval.reference_check). A report that fails verification stops the run.
- Both systems are scored against exactly the same reference text for each report.
- Nothing is removed or corrected to improve a score. The only text changes are the ones named in the results
  (white-space normalisation for CER and word splitting for WER).
- The results file contains no timestamps, so repeating the run gives an identical file.
"""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import PIL

from lumi.eval import text_metrics as tm
from lumi.eval.reference_check import Report, ReferenceError, load_report, verify_report
from lumi.pipelines.ocr.engine import OcrLine, TesseractEngine
from lumi.pipelines.ocr.parser import parse_lab_fields
from lumi.pipelines.ocr.pipeline import LabReportOcrPipeline
from lumi.validation import ValidatedFile

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS = ROOT / "data" / "synthetic" / "lab_reports"
DEFAULT_OUT = ROOT / "docs" / "evaluations" / "ocr_synthetic_results.json"

SYSTEM_DESCRIPTIONS = {
    "lumi_pipeline": (
        "The LUMI lab-report pipeline exactly as the API runs it (lumi.pipelines.ocr.pipeline.LabReportOcrPipeline): "
        "the image is turned upright and converted to greyscale, Tesseract reads it with page-segmentation mode 6 "
        "('one uniform block of text'), words are grouped into lines, and result rows are then parsed from the lines."
    ),
    "plain_tesseract": (
        "Tesseract with its default settings run straight on the original image file: `tesseract IMAGE stdout` "
        "(default page-segmentation mode 3, English). No preprocessing and no parsing."
    ),
}

EVALUATION_PROCEDURE = {
    "reference": "The text printed on each report, one string per printed line, columns left to right joined by one space. It is derived from the same list that draws the image and checked against the image (regeneration plus an independent ink check) before scoring.",
    "edit_distance": "Smallest number of substitutions, deletions and insertions that turns the reference into the system's text. Ties in the split are broken: match or substitution first, then deletion, then insertion.",
    "cer": "Character edit distance divided by the number of reference characters.",
    "wer": "Word edit distance divided by the number of reference words. Words are the pieces left after splitting on white space.",
    "text_levels": {
        "cer_raw": "No change to either text. New lines and any blank lines or form feeds count as characters.",
        "cer_line_aware": "Spaces inside each line collapsed, blank lines dropped, lines kept apart by one new line character.",
        "cer_whitespace_normalised": "PRIMARY. Every run of white space (including new lines) becomes one space; the ends are trimmed.",
        "wer": "Splitting into words ignores white space differences by definition, so it has one level.",
    },
    "never_changed": "Case, punctuation, digits, letters and the order of words are never altered, and no difficult text or wrong value is removed.",
    "aggregates": "micro = total errors over total reference length across all reports (the headline); macro = plain average of the per-report rates.",
    "undefined_rate": "A rate is undefined (null) when the reference is empty but the system's text is not.",
}


@dataclass
class SystemOutput:
    text: str
    lines: list[str]
    fields: list[dict]


# ---------------------------------------------------------------- the two systems


def run_lumi_pipeline(report: Report) -> SystemOutput:
    output = LabReportOcrPipeline(TesseractEngine()).run(ValidatedFile(report.image_bytes, "image/png", report.name), None)
    result = output.result
    return SystemOutput(text=result["extracted_text"], lines=[line for line in result["extracted_text"].split("\n") if line.strip()], fields=result["fields"])


def run_plain_tesseract(report: Report) -> SystemOutput:
    completed = subprocess.run(["tesseract", str(report.image_path), "stdout"], capture_output=True, timeout=120, check=True)
    text = completed.stdout.decode("utf-8", "replace")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # The parser is LUMI's own. It is applied to plain Tesseract's lines only for the secondary field-level comparison.
    fields = [field.to_dict() for field in parse_lab_fields([OcrLine(line, None) for line in lines])]
    return SystemOutput(text=text, lines=lines, fields=fields)


SYSTEMS: dict[str, Callable[[Report], SystemOutput]] = {"lumi_pipeline": run_lumi_pipeline, "plain_tesseract": run_plain_tesseract}


# ---------------------------------------------------------------- scoring one report


def score_text(reference_lines: list[str], hypothesis_text: str) -> dict:
    reference_raw = "\n".join(reference_lines)
    reference_ws, hypothesis_ws = tm.whitespace_normalised(reference_raw), tm.whitespace_normalised(hypothesis_text)
    reference_words, hypothesis_words = tm.words(reference_raw), tm.words(hypothesis_text)
    counts = {
        "cer_raw": tm.character_error_rate(reference_raw, hypothesis_text),
        "cer_line_aware": tm.character_error_rate(tm.line_normalised(reference_raw), tm.line_normalised(hypothesis_text)),
        "cer_whitespace_normalised": tm.character_error_rate(reference_ws, hypothesis_ws),
        "wer": tm.word_error_rate(reference_raw, hypothesis_text),
    }
    return {
        "counts": counts,
        "word_error_categories": tm.categorise_word_errors(reference_words, hypothesis_words),
        "reading_order": tm.reading_order_excess(reference_words, hypothesis_words),
        "character_profile": tm.character_error_profile(reference_ws, hypothesis_ws),
        "lines": tm.lines_reproduced(reference_lines, hypothesis_text),
    }


def score_fields(report: Report, parsed: list[dict]) -> dict:
    """Compare parsed result rows with the ground-truth rows. A blank ground-truth cell is expected as null."""
    truth = [{"test_name": r.test_name, "value": r.value or None, "unit": r.unit or None, "reference_range": r.reference_range or None} for r in report.rows]
    unused = list(range(len(parsed)))
    matched = 0
    correct: Counter = Counter()
    wrong: list[dict] = []
    helped_by_normalisation: list[dict] = []
    silent_errors = flagged_but_all_correct = 0
    for expected in truth:
        index = next((i for i in unused if parsed[i]["test_name"] == expected["test_name"]), None)
        if index is None:
            wrong.append({"row": expected["test_name"], "problem": "row not found"})
            continue
        unused.remove(index)
        row = parsed[index]
        matched += 1
        row_wrong = False
        for key in ("value", "unit", "reference_range"):
            if row[key] == expected[key]:
                correct[key] += 1
            else:
                row_wrong = True
                wrong.append({"row": expected["test_name"], "field": key, "expected": expected[key], "got": row[key]})
        if expected["reference_range"] and row["reference_range"] == expected["reference_range"] and expected["reference_range"] not in row["source_text"]:
            helped_by_normalisation.append({"as_read": row["source_text"], "reported_as": row["reference_range"]})
        if row_wrong and not row["needs_review"]:
            silent_errors += 1
        if not row_wrong and row["needs_review"]:
            flagged_but_all_correct += 1
    return {
        "ground_truth_rows": len(truth),
        "rows_parsed": len(parsed),
        "rows_matched_by_name": matched,
        "fields_exactly_correct": {key: correct[key] for key in ("value", "unit", "reference_range")},
        "field_slots": len(truth) * 3,
        "wrong_or_missing": wrong,
        "spurious_rows": [parsed[i]["test_name"] for i in unused],
        "reference_ranges_correct_only_after_pipeline_spacing_normalisation": helped_by_normalisation,
        "rows_with_a_wrong_field_that_were_not_flagged_for_review": silent_errors,
        "rows_flagged_for_review_although_every_field_was_correct": flagged_but_all_correct,
    }


# ---------------------------------------------------------------- aggregation


def _rate(counts: list[tm.EditCounts]) -> dict:
    total = tm.EditCounts(sum(c.substitutions for c in counts), sum(c.deletions for c in counts), sum(c.insertions for c in counts),
                          sum(c.reference_length for c in counts), sum(c.hypothesis_length for c in counts))
    rates = [c.rate for c in counts if c.rate is not None]
    return {**total.as_dict(), "macro_average_rate": round(sum(rates) / len(rates), 6) if rates else None}


def aggregate_system(per_report: list[dict]) -> dict:
    levels = ("cer_whitespace_normalised", "cer_line_aware", "cer_raw", "wer")
    result = {level: _rate([r["_counts"][level] for r in per_report]) for level in levels}
    categories: Counter = Counter()
    order_excess = word_distance = 0
    lines_ref = lines_ok = 0
    for r in per_report:
        categories.update(r["word_error_categories"]["counts"])
        order_excess += r["reading_order"]["edits_caused_by_word_order"]
        word_distance += r["reading_order"]["word_edit_distance"]
        lines_ref += r["lines"]["reference_lines"]
        lines_ok += r["lines"]["reproduced_exactly"]
    swaps: Counter = Counter()
    by_kind: Counter = Counter()
    for r in per_report:
        by_kind.update(r["character_profile"]["by_kind"])
        for swap in r["character_profile"]["most_common_swaps"]:
            swaps[(swap["reference"], swap["read_as"])] += swap["count"]
    return {
        "reports": len(per_report),
        **result,
        "word_error_categories": {name: categories.get(name, 0) for name in tm.WORD_CATEGORIES},
        "word_edits_caused_by_word_order": order_excess,
        "total_word_edits": word_distance,
        "lines_reproduced_exactly": {"reproduced": lines_ok, "reference_lines": lines_ref},
        "character_errors_by_kind": dict(sorted(by_kind.items())),
        "most_common_character_swaps": [{"reference": a, "read_as": b, "count": c} for (a, b), c in swaps.most_common(8)],
    }


def aggregate_fields(per_report: list[dict]) -> dict:
    expected = sum(r["fields"]["ground_truth_rows"] for r in per_report)
    parsed = sum(r["fields"]["rows_parsed"] for r in per_report)
    matched = sum(r["fields"]["rows_matched_by_name"] for r in per_report)
    slots = sum(r["fields"]["field_slots"] for r in per_report)
    correct = {key: sum(r["fields"]["fields_exactly_correct"][key] for r in per_report) for key in ("value", "unit", "reference_range")}
    return {
        "ground_truth_rows": expected,
        "rows_parsed": parsed,
        "row_recall": round(matched / expected, 6) if expected else None,
        "row_precision": round(matched / parsed, 6) if parsed else None,
        "fields_exactly_correct": correct,
        "field_exact_accuracy": round(sum(correct.values()) / slots, 6) if slots else None,
        "rows_helped_by_range_spacing_normalisation": sum(len(r["fields"]["reference_ranges_correct_only_after_pipeline_spacing_normalisation"]) for r in per_report),
        "rows_with_a_wrong_field_that_were_not_flagged_for_review": sum(r["fields"]["rows_with_a_wrong_field_that_were_not_flagged_for_review"] for r in per_report),
        "rows_flagged_for_review_although_every_field_was_correct": sum(r["fields"]["rows_flagged_for_review_although_every_field_was_correct"] for r in per_report),
    }


# ---------------------------------------------------------------- whole evaluation


def evaluate(reports: list[Report], systems: dict[str, Callable[[Report], SystemOutput]]) -> dict:
    """Score every system on every report against the same reference. Reports must already be verified."""
    if not reports:
        raise ReferenceError("No reports to evaluate.")
    names = [r.name for r in reports]
    if len(set(names)) != len(names):
        raise ReferenceError("Two reports share the same name.")
    reports = sorted(reports, key=lambda r: r.name)

    results: dict[str, dict] = {}
    for system_name, run in systems.items():
        per_report = []
        for report in reports:
            output = run(report)
            reference = report.reference  # the SAME list object content for every system
            scored = score_text(reference, output.text)
            per_report.append({
                "report": report.name,
                "_counts": scored["counts"],
                "scores": {level: counts.as_dict() for level, counts in scored["counts"].items()},
                "word_error_categories": scored["word_error_categories"],
                "reading_order": scored["reading_order"],
                "character_profile": scored["character_profile"],
                "lines": scored["lines"],
                "fields": score_fields(report, output.fields),
                "reference_sha256": hashlib.sha256("\n".join(reference).encode()).hexdigest(),
                "text_read": output.text,
            })
        results[system_name] = {
            "description": SYSTEM_DESCRIPTIONS.get(system_name, ""),
            "aggregate": aggregate_system(per_report),
            "field_level": aggregate_fields(per_report),
            "per_report": [{k: v for k, v in r.items() if k != "_counts"} for r in per_report],
        }
    return results


def dataset_description(reports: list[Report]) -> dict:
    reports = sorted(reports, key=lambda r: r.name)
    reference_text = ["\n".join(r.reference) for r in reports]
    rows = [(row.test_name, row.value, row.unit, row.reference_range) for r in reports for row in r.rows]
    return {
        "reports": len(reports),
        "images": [{"name": r.name, "sha256": hashlib.sha256(r.image_bytes).hexdigest(), "report_id": r.report_id, "rows": len(r.rows), "reference_lines": r.reference} for r in reports],
        "reference_characters_total": sum(len(tm.whitespace_normalised(t)) for t in reference_text),
        "reference_words_total": sum(len(tm.words(t)) for t in reference_text),
        "table_rows_total": len(rows),
        "distinct_table_rows": len(set(rows)),
        "what_the_reports_are": "Computer-drawn synthetic reports: one table layout, one font (Pillow's built-in default at 28 px), black text on white, no noise, skew, stamps, logos or handwriting. Reports 2 and 3 reuse rows from report 1.",
    }


def tesseract_version() -> str:
    try:
        return subprocess.run(["tesseract", "--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
    except (OSError, subprocess.CalledProcessError, IndexError):
        return "unavailable"


def find_reports(folder: Path) -> list[Report]:
    if not folder.is_dir():
        raise ReferenceError(f"The folder {folder} does not exist. Create the synthetic reports with: .venv/bin/python scripts/make_synthetic_lab_reports.py")
    images = sorted(folder.glob("*.png"))
    if not images:
        raise ReferenceError(f"No .png reports in {folder}. Create them with: .venv/bin/python scripts/make_synthetic_lab_reports.py")
    return [load_report(path) for path in images]


def run(reports_folder: Path) -> dict:
    reports = find_reports(reports_folder)
    verification = {r.name: verify_report(r) for r in reports}
    failed = {name: problems for name, problems in verification.items() if problems}
    if failed:
        raise ReferenceError("Reference text does not match the image, so nothing was scored: " + json.dumps(failed))
    return {
        "evaluation": {
            "name": "Lab-report OCR on synthetic reports",
            "format_version": 1,
            "software": {"python": platform.python_version(), "pillow": PIL.__version__, "tesseract": tesseract_version()},
            "reports_folder": reports_folder.name,
        },
        "dataset": dataset_description(reports),
        "reference_verification": {name: ("verified" if not problems else problems) for name, problems in verification.items()},
        "procedure": EVALUATION_PROCEDURE,
        "systems": evaluate(reports, SYSTEMS),
    }


# ---------------------------------------------------------------- printing


def percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def print_summary(results: dict) -> None:
    data = results["dataset"]
    print(f"Reports evaluated: {data['reports']} (reference: {data['reference_characters_total']} characters, {data['reference_words_total']} words, {data['table_rows_total']} table rows of which {data['distinct_table_rows']} are distinct)")
    print("Reference text verified against every image: yes\n")
    names = list(results["systems"])
    print(f"{'PER REPORT':<30}" + "".join(f"{n + ' CER':>26}{n + ' WER':>26}" for n in names))
    for i, report in enumerate(results["systems"][names[0]]["per_report"]):
        row = f"{report['report']:<30}"
        for n in names:
            scores = results["systems"][n]["per_report"][i]["scores"]
            row += f"{percent(scores['cer_whitespace_normalised']['error_rate']):>26}{percent(scores['wer']['error_rate']):>26}"
        print(row)
    print()
    print(f"{'AGGREGATE (micro)':<34}{'CER (primary)':>16}{'CER line-aware':>16}{'CER raw':>12}{'WER':>10}   substitutions/deletions/insertions (CER primary, WER)")
    for n in names:
        a = results["systems"][n]["aggregate"]
        c, w = a["cer_whitespace_normalised"], a["wer"]
        print(f"{n:<34}{percent(c['error_rate']):>16}{percent(a['cer_line_aware']['error_rate']):>16}{percent(a['cer_raw']['error_rate']):>12}{percent(w['error_rate']):>10}   "
              f"{c['substitutions']}/{c['deletions']}/{c['insertions']} of {c['reference_length']} chars; {w['substitutions']}/{w['deletions']}/{w['insertions']} of {w['reference_length']} words")
    print()
    for n in names:
        a, f = results["systems"][n]["aggregate"], results["systems"][n]["field_level"]
        print(f"{n}: word error categories {a['word_error_categories']}; lines exact {a['lines_reproduced_exactly']['reproduced']}/{a['lines_reproduced_exactly']['reference_lines']}; "
              f"field exact accuracy {percent(f['field_exact_accuracy'])} (rows found {percent(f['row_recall'])}, precision {percent(f['row_precision'])})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lab-report OCR evaluation on the synthetic reports.")
    parser.add_argument("--reports", type=Path, default=DEFAULT_REPORTS, help="Folder with the synthetic report images and their .json ground truth.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Where to write the results (JSON).")
    parser.add_argument("--no-write", action="store_true", help="Print only; do not write the results file.")
    args = parser.parse_args(argv)
    try:
        results = run(args.reports)
    except ReferenceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"ERROR: could not run Tesseract ({type(exc).__name__}). Install it with: brew install tesseract", file=sys.stderr)
        return 4
    print_summary(results)
    if not args.no_write:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=2, sort_keys=False) + "\n")
        print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
