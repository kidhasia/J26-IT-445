"""Find the passages that answer a question, and write the extractive answer.

Search: TF-IDF (scikit-learn) over the passages, scored by cosine similarity. A passage is only used if it clears two
checks, so a single shared word is not enough: the score must reach MIN_SCORE, and the passage must contain at least
half of the question's meaningful words. A question needs at least two meaningful words.
Answer: the matching passages themselves, word for word, each tagged [R1], [R2]... No text is generated.
The two numbers below were chosen by hand after trying about a dozen questions; they have not been tuned or evaluated.
"""

import re
from dataclasses import dataclass

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer

from lumi.rag.corpus import Corpus, Passage, plain

CANNOT_ANSWER = "I cannot answer this from the available evidence."
MIN_SCORE = 0.10
MIN_COVERAGE = 0.5
MIN_QUERY_WORDS = 2
MIN_PASSAGE_WORDS = 12  # a very short fragment (one bullet) makes a poor answer on its own, so it is not returned
MAX_SOURCES = 3
MAX_EXCERPT_CHARS = 700
# Words that carry no meaning here ("tell me about ..."), on top of scikit-learn's English stop words.
FILLER = frozenset("tell explain describe say says said show give list mention document documents report project lumi please".split())
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")

# Questions about a person's own health, or asking for diagnosis or treatment. These are refused before any search.
PERSONAL_PHRASES = (
    "do i have", "does my", "is my", "should i", "am i", "can i take", "what should i", "my child", "my son", "my daughter",
    "my baby", "my mole", "my skin", "my lesion", "my rash", "my result", "my results", "my blood", "my test", "my photo",
    "diagnose me", "treat me", "is it cancer", "is this cancer", "is it melanoma", "is this melanoma", "is this safe",
    "what treatment", "which treatment", "how to treat", "how do i treat", "what medicine", "what medication", "what dose",
    "need to see a doctor", "see a doctor",
)
PERSONAL_WORDS = frozenset("prescribe prescription dosage".split())


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


def tokens(text: str) -> list[str]:
    """Lower-case meaningful words, simply stemmed. Stop words and filler are dropped."""
    found = _TOKEN.findall(plain(text).lower())
    return [stem(w) for w in found if w not in ENGLISH_STOP_WORDS and w not in FILLER]


def _analyzer(text: str) -> list[str]:
    words = tokens(text)
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]  # word pairs help with phrases such as "macro f1"


def is_personal_medical_question(question: str) -> bool:
    text = " " + " ".join(_TOKEN.findall(question.lower())) + " "
    return any(f" {phrase} " in text for phrase in PERSONAL_PHRASES) or bool(set(text.split()) & PERSONAL_WORDS)


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
        self.corpus = corpus
        self._texts = [f"{p.title} {p.section} {p.section} {plain(p.text)}" for p in corpus.passages]  # the heading counts double: it says what the passage is about
        self._vectorizer = TfidfVectorizer(analyzer=_analyzer, sublinear_tf=True)
        self._matrix = self._vectorizer.fit_transform(self._texts)
        self._token_sets = [set(tokens(t)) for t in self._texts]

    def search(self, question: str) -> list[Hit]:
        query_tokens = set(tokens(question))
        if len(query_tokens) < MIN_QUERY_WORDS:  # a single generic word is too vague to answer; refuse rather than guess
            return []
        scores = (self._matrix @ self._vectorizer.transform([question]).T).toarray().ravel()
        hits: list[Hit] = []
        for index in scores.argsort()[::-1][: 10 * MAX_SOURCES]:
            score = float(scores[index])
            if score < MIN_SCORE:
                break
            if len(plain(self.corpus.passages[index].text).split()) < MIN_PASSAGE_WORDS:
                continue
            matched = len(query_tokens & self._token_sets[index])
            coverage = matched / len(query_tokens)
            if matched < MIN_QUERY_WORDS or coverage < MIN_COVERAGE:
                continue
            excerpt, truncated = best_excerpt(self.corpus.passages[index], query_tokens)
            hits.append(Hit(self.corpus.passages[index], round(score, 4), round(coverage, 3), excerpt, truncated))
            if len(hits) == MAX_SOURCES:
                break
        return hits


def compose_answer(hits: list[Hit]) -> str:
    """The answer text: each retrieved excerpt, word for word, tagged with its citation number."""
    return "From LUMI project documents (not medical advice):\n" + "\n".join(f"[R{i}] {hit.excerpt}" for i, hit in enumerate(hits, start=1))
