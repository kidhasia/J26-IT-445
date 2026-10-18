"""Rule-based answers drawn only from one supplied analysis. No model, no network, no stored data.

How it works, in order:
1. The question is reduced to lower-case words.
2. If it asks for a diagnosis, treatment, advice, or whether something is "normal", "serious" and so on, it is refused.
   LUMI copies reference ranges as printed and never judges results, so it cannot answer those from evidence.
3. Otherwise each simple topic the question mentions (predicted class, a score, a lab value, missing values, ...) is
   answered from the matching evidence fields. Several topics in one question are all answered (at most five).
4. If no topic matches, or the evidence has no data for it, the answer is exactly CANNOT_ANSWER.

Every number or name in an answer is copied from the evidence (percentages are the evidence's probabilities x 100).
"""

import re
from dataclasses import dataclass, field
from typing import Any

from lumi.qa.evidence import Evidence, LabEvidence, LabField, SkinEvidence

CANNOT_ANSWER = "I cannot answer this from the available evidence."
OUT_OF_SCOPE_NOTE = (
    "LUMI answers only simple factual questions about the supplied analysis result. It does not diagnose, "
    "judge whether a result is normal, or give medical advice."
)
NOT_IN_EVIDENCE_NOTE = "The supplied evidence does not contain the information needed for this question."
MAX_TOPICS = 5
MAX_ANSWER_CHARS = 4000

# Words and phrases that mean "tell me what is wrong / what to do". Checked before anything else.
REFUSAL_WORDS = frozenset(
    "cancer cancerous tumor tumour malignant benign diagnose diagnosed diagnosis disease infection infected treat treated "
    "treatment therapy medicine medication drug drugs dose dosage surgery prognosis cure worry worried serious dangerous "
    "danger urgent emergency healthy unhealthy normal abnormal safe unsafe advice advise recommend recommended "
    "recommendation should symptom symptoms cause causes".split()
)
REFUSAL_PHRASES = (
    "does the child have", "does he have", "does she have", "do they have", "do i have", "have i got", "could it be",
    "might it be", "is it melanoma", "see a doctor", "what does this mean",
)

SCORE_WORDS = ("score", "scores", "confidence", "confident", "probability", "probabilities", "percent", "percentage", "chance")
ALL_SCORES_PHRASES = ("all scores", "all classes", "every class", "each class", "class scores", "scores for all", "other classes", "all six", "all the scores", "list the scores")
CLASS_PHRASES = (
    "predicted class", "predicted skin class", "prediction", "predicted", "predict", "which class", "what class", "top class",
    "highest scoring class", "skin class", "what was the class",
)
MAP_PHRASES = ("attention map", "heatmap", "heat map", "grad cam", "gradcam", "saliency", "where did the model look", "highlighted")
MODEL_PHRASES = ("which model", "what model", "model used", "trained on", "training data", "dataset", "how was it trained", "model name", "held out", "macro f1", "test score")
LIMIT_PHRASES = ("limitation", "limitations", "caveat", "caveats", "can i trust", "how reliable", "reliable", "reliability", "validated", "validation", "known issues", "restrictions")
WARNING_PHRASES = ("warning", "warnings")

MISSING_PHRASES = ("not found", "missing", "blank", "empty", "unreadable", "not read", "could not be read", "absent", "not detected", "not recognised", "not recognized")
REVIEW_PHRASES = ("needs review", "need review", "needs checking", "need checking", "flagged", "to check", "check against", "double check", "verify", "low confidence", "uncertain", "review")
LIST_PHRASES = ("list", "all results", "all tests", "which tests", "what tests", "tests found", "results found", "all values", "every result", "what was found", "how many", "number of rows", "number of results")
CONFIDENCE_PHRASES = ("text confidence", "ocr confidence", "how confident", "confidence", "how accurate")


@dataclass
class Part:
    intent: str
    text: str
    used: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Answer:
    answerable: bool
    text: str
    intents: list[str]
    evidence_used: list[dict[str, Any]]
    note: str | None = None


# ---------------------------------------------------------------- helpers


def normalise(question: str) -> str:
    """' word word word ' (lower case, letters and digits only) so phrases can be found with spaces around them."""
    return " " + " ".join(re.findall(r"[a-z0-9]+", question.lower())) + " "


def has_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(f" {phrase} " in text for phrase in phrases)


def is_out_of_scope(text: str) -> bool:
    return bool(set(text.split()) & REFUSAL_WORDS) or has_any(text, REFUSAL_PHRASES)


def canonical(words_text: str) -> str:
    """Spelling variants of one word are treated as equal when matching a test name ('hemoglobin' = 'haemoglobin')."""
    return words_text.replace("haem", "hem")


def percent(probability: float) -> str:
    return f"{probability * 100:.1f}%"


def strip_code(warning: str) -> str:
    code, sep, rest = warning.partition(":")
    return rest.strip() if sep and re.fullmatch(r"[A-Z_]+", code) else warning


def short_name(name: str) -> str:
    """'Squamous cell carcinoma (includes Bowen's disease)' -> 'squamous cell carcinoma' for matching."""
    return re.sub(r"\(.*?\)", " ", name).strip()


def join_limited(items: list[str], limit: int = 50) -> str:
    shown = items[:limit]
    return "; ".join(shown) + (f"; and {len(items) - limit} more" if len(items) > limit else "")


# ---------------------------------------------------------------- skin


NOT_A_DIAGNOSIS = "This is the model's own relative score between its classes, not a diagnosis."
SCORE_CAVEAT = "It is a relative score between the model's classes, not a calibrated probability or clinical certainty."


def skin_parts(text: str, ev: SkinEvidence) -> list[Part]:
    result = ev.result
    items = result.probabilities
    parts: list[Part] = []

    mentioned = []
    padded = canonical(text)
    for item in items:
        if f" {item.code.lower()} " in padded or f" {' '.join(re.findall(r'[a-z0-9]+', short_name(item.name).lower()))} " in padded:
            mentioned.append(item)

    want_all = has_any(text, ALL_SCORES_PHRASES)
    want_score = has_any(text, SCORE_WORDS) and not want_all
    want_class = has_any(text, CLASS_PHRASES)

    if want_class:
        parts.append(Part("skin.predicted_class",
                          f"The highest-scoring class was {result.predicted_class_name} ({result.predicted_class}). {NOT_A_DIAGNOSIS}",
                          [{"field": "result.predicted_class_name", "value": result.predicted_class_name}, {"field": "result.predicted_class", "value": result.predicted_class}]))
    if want_all:
        listing = "; ".join(f"{item.name} {percent(item.probability)}" for item in items)
        parts.append(Part("skin.all_scores", f"Model scores for all classes: {listing}. They are not calibrated probabilities and do not measure clinical certainty.",
                          [{"field": "result.probabilities", "value": [{"class": i.code, "probability": i.probability} for i in items]}]))
    if want_score:
        if mentioned:
            for item in mentioned[:3]:
                parts.append(Part("skin.class_score", f"The model score for {item.name} ({item.code}) was {percent(item.probability)}. {SCORE_CAVEAT}",
                                  [{"field": "result.probabilities", "value": {"class": item.code, "probability": item.probability}}]))
        else:
            top = max(items, key=lambda i: i.probability)
            score = ev.confidence if ev.confidence is not None else top.probability
            parts.append(Part("skin.top_score", f"The model score for the highest-scoring class ({top.name}) was {percent(score)}. {SCORE_CAVEAT}",
                              [{"field": "confidence" if ev.confidence is not None else "result.probabilities", "value": score}]))

    if has_any(text, MAP_PHRASES):
        info = result.explanation_image
        if info is None:
            parts.append(Part("skin.attention_map", "This evidence does not include an attention map.", [{"field": "result.explanation_image", "value": None}]))
        else:
            where = f" from layer {info.target_layer}" if info.target_layer else ""
            cells = f" ({info.map_cells[0]} by {info.map_cells[1]} cells)" if info.map_cells and len(info.map_cells) == 2 else ""
            target = info.target_class_name or info.target_class or "the highest-scoring class"
            parts.append(Part("skin.attention_map",
                              f"An attention map ({info.method or 'Grad-CAM'}) for {target}{where}{cells} is included. It shows what influenced the model, not what is medically important, and it is not a diagnosis or proof of correctness.",
                              [{"field": "result.explanation_image", "value": {"method": info.method, "target_class": info.target_class, "target_layer": info.target_layer}}]))

    if has_any(text, MODEL_PHRASES) and result.model is not None:
        info = result.model
        bits = [f"model {info.name}" if info.name else None, f"training run {info.run_id}" if info.run_id else None]
        trained = (info.trained_on or {}).get("name")
        if isinstance(trained, str):
            bits.append(f"trained on {trained}")
        evaluation = info.evaluation or {}
        f1, count = evaluation.get("held_out_test_macro_f1"), evaluation.get("held_out_test_images")
        if isinstance(f1, (int, float)) and isinstance(count, int):
            bits.append(f"held-out test macro-F1 {f1:.2f} on {count} images (not a clinical validation)")
        if any(bits):
            parts.append(Part("skin.model", "This result came from " + ", ".join(b for b in bits if b) + ".", [{"field": "result.model", "value": info.name}]))

    if has_any(text, LIMIT_PHRASES) and result.limitations:
        numbered = " ".join(f"({i}) {item}" for i, item in enumerate(result.limitations, start=1))
        notice = f" Clinical boundary: {ev.clinical_boundary_notice}" if ev.clinical_boundary_notice else ""
        parts.append(Part("skin.limitations", f"Limitations stated with this result: {numbered}{notice}", [{"field": "result.limitations", "value": len(result.limitations)}]))

    if has_any(text, WARNING_PHRASES):
        parts.append(warnings_part("skin.warnings", ev))
    return parts


def warnings_part(intent: str, ev: Evidence) -> Part:
    texts = [strip_code(w) for w in ev.warnings]
    body = " ".join(f"({i}) {t}" for i, t in enumerate(texts, start=1)) if texts else "This evidence contains no warnings."
    return Part(intent, body if not texts else f"Warnings attached to this result: {body}", [{"field": "warnings", "value": len(texts)}])


# ---------------------------------------------------------------- lab report


def row_matches(row: LabField, text: str) -> bool:
    name = " ".join(re.findall(r"[a-z0-9]+", row.test_name.lower()))
    return bool(name) and f" {canonical(name)} " in canonical(text)


def review_reason(row: LabField) -> str:
    return "missing: " + ", ".join(m.replace("_", " ") for m in row.missing_fields) if row.missing_fields else "low text confidence"


def row_part(row: LabField, text: str) -> Part:
    want_unit = has_any(text, ("unit", "units"))
    want_range = has_any(text, ("range", "reference", "ref"))
    want_value = has_any(text, ("value", "result", "reported", "level", "measured", "reading", "read"))
    everything = not (want_unit or want_range or want_value)
    sentences: list[str] = []
    if want_value or everything:
        if row.value is None:
            sentences.append(f"{row.test_name}: no result value was found on the report (the cell may be blank or unreadable).")
        else:
            unit = f" {row.unit}" if row.unit else " (no unit was found)"
            sentences.append(f"{row.test_name}: the reported value was {row.value}{unit}.")
    if want_unit and not (want_value or everything):
        sentences.append(f"{row.test_name}: " + (f"the unit was {row.unit}." if row.unit else "no unit was found on the report."))
    if want_range or everything:
        sentences.append("The reference range as printed is " + (f"{row.reference_range}." if row.reference_range else "not found on the report."))
    if row.needs_review:
        sentences.append(f"This row is flagged for review ({review_reason(row)}); check it against the original report.")
    used = [{"field": f"result.fields[{row.line_number}]", "value": {"test_name": row.test_name, "value": row.value, "unit": row.unit, "reference_range": row.reference_range}}]
    return Part("lab.row", " ".join(sentences), used)


def lab_parts(text: str, ev: LabEvidence) -> list[Part]:
    result = ev.result
    rows = result.fields
    parts: list[Part] = []
    tests = [row for row in rows if row_matches(row, text)]

    if tests:
        parts += [row_part(row, text) for row in tests[:3]]
    if has_any(text, MISSING_PHRASES):
        asks = (
            ("value", has_any(text, ("value", "values", "result", "results"))),
            ("unit", has_any(text, ("unit", "units"))),
            ("reference_range", has_any(text, ("range", "ranges", "reference"))),
        )
        kinds = [kind for kind, asked in asks if asked] or ["value", "unit", "reference_range"]  # nothing named: all kinds
        found = [f"{row.test_name} ({kind.replace('_', ' ')})" for row in rows for kind in kinds if kind in row.missing_fields]
        label = " / ".join(k.replace("_", " ") for k in kinds)
        body = f"Not found: {join_limited(found)}." if found else f"No {label} entries were reported as missing in this evidence."
        parts.append(Part("lab.missing", body, [{"field": "result.fields[].missing_fields", "value": found}]))

    if has_any(text, REVIEW_PHRASES) and not tests:
        flagged = [f"{row.test_name} ({review_reason(row)})" for row in rows if row.needs_review]
        parts.append(Part("lab.review", f"Rows flagged for review: {join_limited(flagged)}." if flagged else "No rows were flagged for review.",
                          [{"field": "result.fields[].needs_review", "value": flagged}]))

    if has_any(text, LIST_PHRASES) and not tests:
        if has_any(text, ("how many", "number of rows", "number of results")):
            parts.append(Part("lab.count", f"{len(rows)} result row(s) were found.", [{"field": "result.fields", "value": len(rows)}]))
        else:
            shown = [f"{row.test_name} {row.value if row.value is not None else 'value not found'}{' ' + row.unit if row.unit and row.value is not None else ''}" for row in rows]
            parts.append(Part("lab.list", f"{len(rows)} result row(s) were found: {join_limited(shown)}." if rows else "No result rows were found.",
                              [{"field": "result.fields", "value": len(rows)}]))

    if has_any(text, CONFIDENCE_PHRASES) and result.mean_ocr_confidence is not None:
        parts.append(Part("lab.text_confidence",
                          f"The average text-reading confidence was {result.mean_ocr_confidence} out of 100. It describes how sure the text reader was, not whether the values are correct.",
                          [{"field": "result.mean_ocr_confidence", "value": result.mean_ocr_confidence}]))

    if has_any(text, LIMIT_PHRASES):
        pieces = [result.reference_range_note] if result.reference_range_note else []
        pieces += [strip_code(w) for w in ev.warnings]
        if ev.clinical_boundary_notice:
            pieces.append(f"Clinical boundary: {ev.clinical_boundary_notice}")
        if pieces:
            parts.append(Part("lab.limitations", "Limitations stated with this result: " + " ".join(f"({i}) {p}" for i, p in enumerate(pieces, start=1)),
                              [{"field": "result.reference_range_note", "value": bool(result.reference_range_note)}, {"field": "warnings", "value": len(ev.warnings)}]))

    if has_any(text, WARNING_PHRASES):
        parts.append(warnings_part("lab.warnings", ev))
    return parts


# ---------------------------------------------------------------- entry point


def answer_question(question: str, evidence: Evidence) -> Answer:
    text = normalise(question)
    if is_out_of_scope(text):
        return Answer(False, CANNOT_ANSWER, [], [], OUT_OF_SCOPE_NOTE)
    parts = skin_parts(text, evidence) if isinstance(evidence, SkinEvidence) else lab_parts(text, evidence)
    parts = [p for p in parts if p.text][:MAX_TOPICS]
    if not parts:
        return Answer(False, CANNOT_ANSWER, [], [], NOT_IN_EVIDENCE_NOTE)
    body = " ".join(p.text for p in parts)
    if len(body) > MAX_ANSWER_CHARS:
        body = body[: MAX_ANSWER_CHARS - 2].rstrip() + " …"
    return Answer(True, body, [p.intent for p in parts], [u for p in parts for u in p.used])
