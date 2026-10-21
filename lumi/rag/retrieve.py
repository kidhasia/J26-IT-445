"""Find the passages that answer a question, and write the extractive answer.

Search: TF-IDF (scikit-learn) over the passages. A passage's score is its body match plus half of its heading match, so a passage
under a heading that is about the question ranks well. A passage is only used if it clears these checks, so a shared common word
is not enough:
  - the score must reach MIN_SCORE;
  - the passage must contain at least MIN_QUERY_WORDS of the question's meaningful words, and at least MIN_COVERAGE of their total
    weight, where a word's weight is how rare it is in the corpus (a word the corpus never uses counts as the rarest of all);
  - it must contain the question's rarest word(s): if the question asks about "solar panels" and the documents never mention them,
    matching "limitations" or "model" is not evidence.
A question needs at least two meaningful words.
Answer: the matching passages themselves, word for word, each tagged [R1], [R2]... No text is generated.
The two numbers below were chosen by hand after trying about a dozen questions; they have not been tuned or evaluated.
"""

import re
from dataclasses import dataclass

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer

from lumi.rag.corpus import Corpus, Passage, plain
from lumi.rag.safety import is_personal_medical_question  # noqa: F401  (re-exported: the guard runs before any search)

CANNOT_ANSWER = "I cannot answer this from the available evidence."
MIN_SCORE = 0.10
MIN_COVERAGE = 0.5
MIN_QUERY_WORDS = 2
HEADING_WEIGHT = 1.0  # a matching section heading counts as much as a matching body: it says what the passage is about
RAREST_SHARE = 0.9  # 'the question's rarest word(s)' = words at least this share as rare as the rarest
MIN_PASSAGE_WORDS = 12  # a very short fragment (one bullet) makes a poor answer on its own, so it is not returned
MAX_SOURCES = 3
MAX_EXCERPT_CHARS = 700
# Words that carry no meaning here ("tell me about ..."), on top of scikit-learn's English stop words.
FILLER = frozenset(
    "tell explain describe say says said show give list mention document documents report project lumi please "
    "came come comes coming get gets got make makes made take takes took long often kind kinds thing things way ways do does did doing done".split()
)
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")

def stem(word: str) -> str:
    """A very small stemmer so 'image' and 'images', or 'train' and 'trained', match. It only strips a few endings and
    never leaves fewer than four letters."""
    word = word.replace("haem", "hem")
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 5 and word.endswith(("sses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    if len(word) > 7 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 5 and word.endswith("ed"):
        return word[:-2]
    return word


def _us_to_uk(word: str) -> str:
    """'optimizer' -> 'optimiser' (the documents use British spelling)."""
    if len(word) > 6:
        return re.sub(r"iz(e|ed|er|ers|es|ing|ation)$", r"is\1", word)
    return word


def tokens(text: str) -> list[str]:
    """Lower-case meaningful words, simply stemmed. Stop words and filler are dropped. A word such as 'unimplemented' also
    yields 'implement', so a question about what is "implemented" can find text about what is "unimplemented"."""
    out: list[str] = []
    for word in _TOKEN.findall(plain(text).lower()):
        if word in ENGLISH_STOP_WORDS or word in FILLER:
            continue
        word = _us_to_uk(word)
        out.append(stem(word))
        prefixed = re.fullmatch(r"un([a-z]{5,}(?:ed|able|ly))", word)
        if prefixed:
            out.append(stem(prefixed.group(1)))
    return out


def _analyzer(text: str) -> list[str]:
    words = tokens(text)
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]  # word pairs help with phrases such as "macro f1"


@dataclass(frozen=True)
class Hit:
    passage: Passage
    score: float
    coverage: float
    excerpt: str
    truncated: bool


def best_excerpt(passage: Passage, query_tokens: set[str]) -> tuple[str, bool]:
    """The passage as plain text. If it is longer than MAX_EXCERPT_CHARS, the run of whole lines (or sentences) that
    overlaps the question most; always a contiguous piece of the original wording."""
    text = plain(passage.text)
    if len(text) <= MAX_EXCERPT_CHARS:
        return text, False
    units: list[str] = []  # whole lines, or sentences of a long line
    joiners: list[str] = []  # what goes before each unit: a line break between lines, a space between sentences of one line
    for line in text.splitlines():
        parts = [s for s in re.split(r"(?<=[.!?])\s+", line) if s.strip()] if len(line) > 200 else ([line] if line.strip() else [])
        for index, part in enumerate(parts):
            units.append(part)
            joiners.append(" " if index else "\n")
    best, best_score = (0, 1), -1.0
    for start in range(len(units)):
        size = 0
        for end in range(start, len(units)):
            size += len(units[end]) + 1
            if size > MAX_EXCERPT_CHARS and end > start:
                break
            score = sum(1 for t in tokens(" ".join(units[start : end + 1])) if t in query_tokens) / (1 + 0.002 * size)
            if score > best_score:
                best, best_score = (start, end + 1), score
    chosen = "".join((joiners[i] if i > best[0] else "") + units[i] for i in range(best[0], best[1]))
    return chosen, True


class Retriever:
    def __init__(self, corpus: Corpus):
        import math

        self.corpus = corpus
        bodies = [plain(p.text) for p in corpus.passages]
        headings = [f"{p.title} {p.section}" for p in corpus.passages]
        self._vectorizer = TfidfVectorizer(analyzer=_analyzer, sublinear_tf=True)
        self._vectorizer.fit([f"{h} {b}" for h, b in zip(headings, bodies)])
        self._body = self._vectorizer.transform(bodies)
        self._heading = self._vectorizer.transform(headings)
        self._token_sets = [set(tokens(f"{h} {b}")) for h, b in zip(headings, bodies)]
        document_frequency: dict[str, int] = {}
        for tokens_in_passage in self._token_sets:
            for token in tokens_in_passage:
                document_frequency[token] = document_frequency.get(token, 0) + 1
        count = len(self._token_sets)
        # How rare a word is in this corpus. A word the corpus never uses ("solar") is the rarest of all.
        self._weight = lambda token: math.log((count + 1) / (document_frequency.get(token, 0) + 1)) + 1.0

    def search(self, question: str) -> list[Hit]:
        query_tokens = set(tokens(question))
        if len(query_tokens) < MIN_QUERY_WORDS:  # a single generic word is too vague to answer; refuse rather than guess
            return []
        query = self._vectorizer.transform([question]).T
        scores = (self._body @ query).toarray().ravel() + HEADING_WEIGHT * (self._heading @ query).toarray().ravel()
        weights = {token: self._weight(token) for token in query_tokens}
        total = sum(weights.values())
        rarest = {token for token, weight in weights.items() if weight >= RAREST_SHARE * max(weights.values())}
        hits: list[Hit] = []
        for index in scores.argsort()[::-1][: 10 * MAX_SOURCES]:
            score = float(scores[index])
            if score < MIN_SCORE:
                break
            if len(plain(self.corpus.passages[index].text).split()) < MIN_PASSAGE_WORDS:
                continue
            present = query_tokens & self._token_sets[index]
            coverage = sum(weights[token] for token in present) / total
            if len(present) < MIN_QUERY_WORDS or coverage < MIN_COVERAGE or not (rarest & present):
                continue
            excerpt, truncated = best_excerpt(self.corpus.passages[index], query_tokens)
            hits.append(Hit(self.corpus.passages[index], round(score, 4), round(coverage, 3), excerpt, truncated))
            if len(hits) == MAX_SOURCES:
                break
        return hits


def compose_answer(hits: list[Hit]) -> str:
    """The answer text: each retrieved excerpt, word for word, tagged with its citation number."""
    return "From LUMI project documents (not medical advice):\n" + "\n".join(f"[R{i}] {hit.excerpt}" for i, hit in enumerate(hits, start=1))
