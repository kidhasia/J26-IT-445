"""Edit distance, CER, WER and error categories: hand-worked examples, an independent implementation, and edge cases."""

import random
from functools import lru_cache

import pytest

from lumi.eval import text_metrics as tm
from lumi.eval.text_metrics import EditCounts, Op


def independent_distance(a: str, b: str) -> int:
    """A deliberately different implementation (recursive with memory) used only to check the real one."""

    @lru_cache(maxsize=None)
    def go(i: int, j: int) -> int:
        if i == 0:
            return j
        if j == 0:
            return i
        return min(go(i - 1, j) + 1, go(i, j - 1) + 1, go(i - 1, j - 1) + (a[i - 1] != b[j - 1]))

    return go(len(a), len(b))


# ---------------------------------------------------------------- the maths


def test_distance_matches_an_independent_implementation_on_many_random_pairs():
    rng = random.Random(1234)
    for _ in range(400):
        a = "".join(rng.choice("abc ") for _ in range(rng.randint(0, 14)))
        b = "".join(rng.choice("abc ") for _ in range(rng.randint(0, 14)))
        counts = tm.edit_counts(a, b)
        assert counts.distance == independent_distance(a, b), (a, b)
        assert (counts.reference_length, counts.hypothesis_length) == (len(a), len(b))


def test_alignment_really_turns_the_reference_into_the_hypothesis():
    rng = random.Random(99)
    for _ in range(200):
        a = "".join(rng.choice("xyz") for _ in range(rng.randint(0, 10)))
        b = "".join(rng.choice("xyz") for _ in range(rng.randint(0, 10)))
        ops = tm.align(a, b)
        assert "".join(a[o.ref_index] for o in ops if o.ref_index is not None) == a  # every reference item appears once
        assert "".join(b[o.hyp_index] for o in ops if o.hyp_index is not None) == b  # every hypothesis item appears once
        assert all((a[o.ref_index] == b[o.hyp_index]) == (o.kind == "match") for o in ops if o.kind in ("match", "sub"))


def test_classic_hand_worked_examples():
    kitten = tm.edit_counts("kitten", "sitting")  # k->s, e->i substituted, g inserted
    assert (kitten.substitutions, kitten.deletions, kitten.insertions, kitten.distance) == (2, 0, 1, 3)
    assert kitten.rate == 0.5
    flaw = tm.edit_counts("flaw", "lawn")  # f deleted, n inserted
    assert (flaw.substitutions, flaw.deletions, flaw.insertions) == (0, 1, 1)
    assert tm.edit_counts("saturday", "sunday").distance == 3


def test_identical_and_totally_different_texts():
    assert tm.edit_counts("same text", "same text").distance == 0 and tm.edit_counts("same text", "same text").rate == 0.0
    different = tm.edit_counts("abc", "xyz")
    assert (different.substitutions, different.rate) == (3, 1.0)


def test_tie_break_rule_is_fixed_and_documented():
    swap = tm.edit_counts("ab", "ba")  # could be 2 substitutions or 1 deletion + 1 insertion; the rule picks substitutions
    assert (swap.substitutions, swap.deletions, swap.insertions) == (2, 0, 0)
    assert tm.align("ab", "ba") == tm.align("ab", "ba")  # deterministic


# ---------------------------------------------------------------- empty and extreme inputs


def test_both_empty_is_zero_error():
    counts = tm.edit_counts("", "")
    assert counts.distance == 0 and counts.rate == 0.0 and counts.reference_length == 0
    assert tm.character_error_rate("", "").rate == 0.0 and tm.word_error_rate("", "").rate == 0.0


def test_nothing_recognised_is_total_deletion():
    counts = tm.character_error_rate("abc", "")
    assert (counts.deletions, counts.rate) == (3, 1.0)
    assert tm.word_error_rate("one two three", "").rate == 1.0


def test_empty_reference_with_text_has_undefined_rate_but_counted_insertions():
    counts = tm.character_error_rate("", "abc")
    assert counts.insertions == 3 and counts.rate is None
    assert counts.as_dict()["error_rate"] is None and counts.as_dict()["insertions"] == 3


def test_rate_can_exceed_one_when_there_are_many_insertions():
    counts = tm.edit_counts("a", "abcd")
    assert counts.insertions == 3 and counts.rate == 3.0


def test_unicode_characters_count_once_and_case_matters():
    assert tm.character_error_rate("café", "cafe").distance == 1
    assert tm.character_error_rate("µg/L", "ug/L").substitutions == 1
    assert tm.character_error_rate("Sodium", "sodium").distance == 1  # case is never folded


# ---------------------------------------------------------------- words


def test_word_error_rate_examples():
    assert tm.word_error_rate("the cat sat", "the cat sat on").as_dict()["insertions"] == 1
    assert tm.word_error_rate("the cat sat", "the cat sat on").rate == pytest.approx(1 / 3)
    two = tm.word_error_rate("the cat sat", "a cat")  # the->a substituted, sat deleted
    assert (two.substitutions, two.deletions, two.insertions) == (1, 1, 0) and two.rate == pytest.approx(2 / 3)


def test_words_are_split_on_any_white_space_but_punctuation_stays_attached():
    assert tm.word_error_rate("a  b\tc\nd", "a b c d").distance == 0
    assert tm.word_error_rate("cat sat", "cat, sat").distance == 1  # the comma is part of the word, not removed
    assert tm.words("11.5 - 15.5") == ["11.5", "-", "15.5"]


def test_normalisation_changes_only_white_space():
    messy = "  SYNTHETIC \t TEST\n\n REPORT\x0c\xa0END  "
    assert tm.whitespace_normalised(messy) == "SYNTHETIC TEST REPORT END"
    assert tm.whitespace_normalised("Cat, Dog.\n12.5") == "Cat, Dog. 12.5"  # case, punctuation, digits untouched
    assert tm.line_normalised("a  b\n\n  c   d \n") == "a b\nc d"
    assert tm.line_normalised("") == "" and tm.whitespace_normalised("   \n ") == ""


# ---------------------------------------------------------------- categories of mistakes


def categories(reference: str, hypothesis: str) -> dict:
    return tm.categorise_word_errors(tm.words(reference), tm.words(hypothesis))["counts"]


def only(counts: dict) -> dict:
    return {name: value for name, value in counts.items() if value}


def test_moved_spaces_are_a_word_boundary_error_not_a_misread():
    assert only(categories("mg/L < 5", "mg/L <5")) == {"word_boundary": 2}
    assert only(categories("75 - 95", "75-95")) == {"word_boundary": 3}  # three reference words against one word read: 1 substitution + 2 deletions
    assert only(categories("3.9 - 5.8", "3.9 -5.8")) == {"word_boundary": 2}
    assert only(categories("a bc", "ab c")) == {"word_boundary": 2}


def test_numbers_and_words_are_told_apart():
    assert only(categories("Hb 12.1 g/dL", "Hb g/dL")) == {"missing_number": 1}
    assert only(categories("Hb g/dL", "Hb 12.1 g/dL")) == {"extra_number": 1}
    assert only(categories("Hb 12.1 g/dL", "Hb 12.7 g/dL")) == {"wrong_number": 1}
    assert only(categories("Hb 12.1 g/dL", "Hb l2.1 g/dL")) == {"wrong_number": 1}  # a digit read as a letter still involves a number
    assert only(categories("Haemoglobin 12.1", "Haemoglobln 12.1")) == {"wrong_characters_in_word": 1}
    assert only(categories("Sodium 139 mmol/L", "139 mmol/L")) == {"missing_word": 1}
    assert only(categories("Sodium 139", "Sodium 139 extra")) == {"extra_word": 1}


def test_categories_always_add_up_to_the_word_edit_distance():
    rng = random.Random(7)
    vocabulary = ["12.1", "g/dL", "Hb", "<", "5", "<5", "mmol/L", "-", "3.9", "Sodium"]
    for _ in range(300):
        ref = [rng.choice(vocabulary) for _ in range(rng.randint(0, 9))]
        hyp = [rng.choice(vocabulary) for _ in range(rng.randint(0, 9))]
        total = sum(tm.categorise_word_errors(ref, hyp)["counts"].values())
        assert total == tm.edit_counts(ref, hyp).distance, (ref, hyp)


def test_examples_are_recorded_for_each_kind_of_error():
    result = tm.categorise_word_errors(tm.words("C-reactive 4 mg/L < 5"), tm.words("C-reactive 4 mg/L <5"))
    assert result["examples"]["word_boundary"] == [{"reference": "< 5", "read_as": "<5"}]


def test_reading_order_errors_are_separated_from_wrong_words():
    ordered = tm.reading_order_excess(tm.words("a b c d"), tm.words("a b c d"))
    assert ordered["edits_caused_by_word_order"] == 0 and not ordered["same_words_different_order"]
    swapped = tm.reading_order_excess(tm.words("one two three four"), tm.words("four three two one"))
    assert swapped["same_words_different_order"] and swapped["edits_needed_if_order_were_ignored"] == 0
    assert swapped["edits_caused_by_word_order"] == swapped["word_edit_distance"] > 0
    wrong_word = tm.reading_order_excess(tm.words("a b c"), tm.words("a x c"))
    assert wrong_word["edits_caused_by_word_order"] == 0 and wrong_word["word_edit_distance"] == 1


def test_order_excess_is_never_negative():
    rng = random.Random(3)
    for _ in range(300):
        ref = [rng.choice("abcd") for _ in range(rng.randint(0, 8))]
        hyp = [rng.choice("abcd") for _ in range(rng.randint(0, 8))]
        assert tm.reading_order_excess(ref, hyp)["edits_caused_by_word_order"] >= 0


def test_character_profile_says_what_kind_of_characters_went_wrong():
    profile = tm.character_error_profile("75 - 95 mg", "75-95 rg")
    assert profile["by_kind"]["deleted_space"] == 2
    assert profile["by_kind"]["substituted_letter"] == 1  # m -> r
    assert {"reference": "m", "read_as": "r", "count": 1} in profile["most_common_swaps"]
    assert tm.character_error_profile("abc", "abc") == {"by_kind": {}, "most_common_swaps": []}


def test_lines_reproduced_counts_whole_lines_and_lists_the_misses():
    result = tm.lines_reproduced(["a b", "c d", "c d", "e"], "a  b\n\nc d\nx y\n")
    assert result["reference_lines"] == 4 and result["reproduced_exactly"] == 2  # "c d" appears only once in the text
    assert result["not_reproduced"] == ["c d", "e"]
    assert tm.lines_reproduced([], "anything")["reproduced_exactly"] == 0
    assert tm.lines_reproduced(["a"], "")["reproduced_exactly"] == 0


def test_edit_counts_dataclass_dict_is_complete():
    row = EditCounts(1, 2, 3, 12, 14).as_dict()
    assert row == {"substitutions": 1, "deletions": 2, "insertions": 3, "edit_distance": 6, "reference_length": 12, "hypothesis_length": 14, "error_rate": 0.5}
    assert Op("match", 0, 0).kind == "match"
