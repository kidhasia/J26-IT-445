"""Standard text-error metrics for OCR evaluation: edit distance, CER, WER and error categories.

Definitions (the usual ones):
  Edit distance  = the smallest number of single-item edits that turn the reference into the hypothesis.
                   An edit is one SUBSTITUTION (a reference item replaced by a different one), one DELETION (a reference
                   item missing from the hypothesis) or one INSERTION (an extra item in the hypothesis). Matches cost 0.
  CER            = edit distance over CHARACTERS / number of characters in the reference.
  WER            = edit distance over WORDS      / number of words in the reference.
  Both can exceed 1.0 if the hypothesis has many insertions.

Counting rule for S, D and I: the total is unique, but the split can tie (for example "ab" -> "ba" is two substitutions
or one deletion plus one insertion). To make results reproducible, the alignment is traced back from the end of both
sequences and, when several moves give the same cost, prefers (1) match or substitution, then (2) deletion, then
(3) insertion. The same rule is used for every system and every report.

Nothing here changes case, removes punctuation or maps look-alike characters. Words are the pieces left after splitting
on white space.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Op:
    kind: str  # "match", "sub", "del" or "ins"
    ref_index: int | None  # position in the reference (None for an insertion)
    hyp_index: int | None  # position in the hypothesis (None for a deletion)


@dataclass(frozen=True)
class EditCounts:
    substitutions: int
    deletions: int
    insertions: int
    reference_length: int
    hypothesis_length: int

    @property
    def distance(self) -> int:
        return self.substitutions + self.deletions + self.insertions

    @property
    def rate(self) -> float | None:
        """distance / reference length. 0.0 when both are empty. None (undefined) when the reference is empty but the
        hypothesis is not, because a rate cannot be divided by zero; the insertions are still counted."""
        if self.reference_length == 0:
            return 0.0 if self.distance == 0 else None
        return self.distance / self.reference_length

    def as_dict(self) -> dict:
        return {
            "substitutions": self.substitutions,
            "deletions": self.deletions,
            "insertions": self.insertions,
            "edit_distance": self.distance,
            "reference_length": self.reference_length,
            "hypothesis_length": self.hypothesis_length,
            "error_rate": None if self.rate is None else round(self.rate, 6),
        }


def align(reference: Sequence, hypothesis: Sequence) -> list[Op]:
    """Minimum-edit alignment of two sequences (strings, or lists of words). Ties are broken as described above."""
    n, m = len(reference), len(hypothesis)
    cost = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        cost[i][0] = i
    for j in range(1, m + 1):
        cost[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            same = 0 if reference[i - 1] == hypothesis[j - 1] else 1
            cost[i][j] = min(cost[i - 1][j - 1] + same, cost[i - 1][j] + 1, cost[i][j - 1] + 1)

    ops: list[Op] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and cost[i][j] == cost[i - 1][j - 1] + (0 if reference[i - 1] == hypothesis[j - 1] else 1):
            ops.append(Op("match" if reference[i - 1] == hypothesis[j - 1] else "sub", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and cost[i][j] == cost[i - 1][j] + 1:
            ops.append(Op("del", i - 1, None))
            i -= 1
        else:
            ops.append(Op("ins", None, j - 1))
            j -= 1
    ops.reverse()
    return ops


def count_edits(ops: list[Op], reference_length: int, hypothesis_length: int) -> EditCounts:
    kinds = Counter(op.kind for op in ops)
    return EditCounts(kinds["sub"], kinds["del"], kinds["ins"], reference_length, hypothesis_length)


def edit_counts(reference: Sequence, hypothesis: Sequence) -> EditCounts:
    return count_edits(align(reference, hypothesis), len(reference), len(hypothesis))


# ---------------------------------------------------------------- text preparation (the only changes ever made)


def whitespace_normalised(text: str) -> str:
    """Every run of white space (spaces, tabs, new lines, form feeds, non-breaking spaces) becomes one space and the
    ends are trimmed. Case, punctuation, digits and letters are left exactly as they are."""
    return " ".join(text.split())


def line_normalised(text: str) -> str:
    """Keeps the line structure: spaces inside each line are collapsed, empty lines are dropped, lines are joined with
    a new line (which then counts as one character)."""
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def words(text: str) -> list[str]:
    return text.split()


def character_error_rate(reference: str, hypothesis: str) -> EditCounts:
    return edit_counts(reference, hypothesis)


def word_error_rate(reference: str, hypothesis: str) -> EditCounts:
    return edit_counts(words(reference), words(hypothesis))


# ---------------------------------------------------------------- what kind of mistakes were made


def _has_digit(text: str) -> bool:
    return any(ch.isdigit() for ch in text)


def _character_class(ch: str) -> str:
    if ch.isspace():
        return "space"
    if ch.isdigit():
        return "digit"
    if ch.isalpha():
        return "letter"
    return "punctuation"


WORD_CATEGORIES = (
    "missing_word",
    "missing_number",
    "extra_word",
    "extra_number",
    "wrong_characters_in_word",
    "wrong_number",
    "word_boundary",
)


def categorise_word_errors(reference_words: list[str], hypothesis_words: list[str], example_limit: int = 5) -> dict:
    """Group every word-level edit into a kind of mistake. Units are word edits, so the categories add up exactly to
    the word edit distance.

    missing_word / missing_number     a reference word (or one containing a digit) is absent from the hypothesis
    extra_word / extra_number         an extra word (or one containing a digit) appears in the hypothesis
    wrong_characters_in_word          a word is read as a different word with no digits involved
    wrong_number                      a word containing a digit is read as something else, or the reverse
    word_boundary                     a stretch of words that is the same text with spaces moved ("< 5" read as "<5")
    """
    ops = align(reference_words, hypothesis_words)
    counts: Counter = Counter()
    examples: dict[str, list[dict]] = {name: [] for name in WORD_CATEGORIES}

    def record(category: str, ref_text: str, hyp_text: str, edits: int) -> None:
        counts[category] += edits
        if len(examples[category]) < example_limit:
            examples[category].append({"reference": ref_text, "read_as": hyp_text})

    block: list[Op] = []

    def flush() -> None:
        if not block:
            return
        ref_part = [reference_words[o.ref_index] for o in block if o.ref_index is not None]
        hyp_part = [hypothesis_words[o.hyp_index] for o in block if o.hyp_index is not None]
        if ref_part and hyp_part and len(block) >= 2 and "".join(ref_part) == "".join(hyp_part):
            record("word_boundary", " ".join(ref_part), " ".join(hyp_part), len(block))
        else:
            for op in block:
                ref_word = reference_words[op.ref_index] if op.ref_index is not None else ""
                hyp_word = hypothesis_words[op.hyp_index] if op.hyp_index is not None else ""
                if op.kind == "del":
                    record("missing_number" if _has_digit(ref_word) else "missing_word", ref_word, "", 1)
                elif op.kind == "ins":
                    record("extra_number" if _has_digit(hyp_word) else "extra_word", "", hyp_word, 1)
                else:
                    record("wrong_number" if (_has_digit(ref_word) or _has_digit(hyp_word)) else "wrong_characters_in_word", ref_word, hyp_word, 1)
        block.clear()

    for op in ops:
        if op.kind == "match":
            flush()
        else:
            block.append(op)
    flush()
    return {"counts": {name: counts.get(name, 0) for name in WORD_CATEGORIES}, "examples": {k: v for k, v in examples.items() if v}}


def reading_order_excess(reference_words: list[str], hypothesis_words: list[str]) -> dict:
    """How much of the word error is only about ORDER?

    Ignoring order, the fewest edits needed is max(reference words missing from the hypothesis, hypothesis words not in
    the reference), because one substitution can repair one of each. Whatever the real edit distance adds on top of
    that is caused by words being in the wrong order (or in the wrong place). It is zero when the right words appear
    in the right order."""
    distance = edit_counts(reference_words, hypothesis_words).distance
    shared = sum((Counter(reference_words) & Counter(hypothesis_words)).values())
    unmatched_reference = len(reference_words) - shared
    unmatched_hypothesis = len(hypothesis_words) - shared
    order_free = max(unmatched_reference, unmatched_hypothesis)
    return {
        "word_edit_distance": distance,
        "edits_needed_if_order_were_ignored": order_free,
        "edits_caused_by_word_order": distance - order_free,
        "same_words_different_order": unmatched_reference == 0 and unmatched_hypothesis == 0 and distance > 0,
    }


def character_error_profile(reference: str, hypothesis: str, top: int = 8) -> dict:
    """Character-level view: which kinds of characters were deleted, inserted or substituted, and the commonest swaps."""
    ops = align(reference, hypothesis)
    by_kind: Counter = Counter()
    swaps: Counter = Counter()
    for op in ops:
        if op.kind == "del":
            by_kind[("deleted", _character_class(reference[op.ref_index]))] += 1
        elif op.kind == "ins":
            by_kind[("inserted", _character_class(hypothesis[op.hyp_index]))] += 1
        elif op.kind == "sub":
            by_kind[("substituted", _character_class(reference[op.ref_index]))] += 1
            swaps[(reference[op.ref_index], hypothesis[op.hyp_index])] += 1
    return {
        "by_kind": {f"{kind}_{cls}": count for (kind, cls), count in sorted(by_kind.items())},
        "most_common_swaps": [{"reference": a, "read_as": b, "count": c} for (a, b), c in swaps.most_common(top)],
    }


def lines_reproduced(reference_lines: list[str], hypothesis_text: str) -> dict:
    """How many reference lines appear as a complete line in the hypothesis (spaces inside a line collapsed)."""
    available = Counter(" ".join(line.split()) for line in hypothesis_text.splitlines() if line.strip())
    exact = 0
    missed: list[str] = []
    for line in reference_lines:
        key = " ".join(line.split())
        if available[key] > 0:
            available[key] -= 1
            exact += 1
        else:
            missed.append(line)
    return {"reference_lines": len(reference_lines), "reproduced_exactly": exact, "not_reproduced": missed}
