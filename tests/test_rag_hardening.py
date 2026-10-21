"""Hardening of the retrieval demo: the diagnostic-request guard, relevance filtering, ranking, and citations.

As with test_rag.py, the questions were written by the author of the retriever. These tests show the code behaves as written;
they do not measure retrieval quality, and the guard is a conservative word-and-phrase check, not a medical safety classifier.
"""

import dataclasses
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumi.main import create_app
from lumi.rag.corpus import load_corpus, plain, split_markdown
from lumi.rag.retrieve import CANNOT_ANSWER, Retriever, is_personal_medical_question, tokens
from tests.conftest import AUTH_HEADERS

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "knowledge" / "manifest.json"
URL = "/api/v1/rag-demo"


@pytest.fixture(scope="module")
def corpus():
    return load_corpus(MANIFEST)


@pytest.fixture(scope="module")
def retriever(corpus):
    return Retriever(corpus)


@pytest.fixture
def api(settings):
    return TestClient(create_app(settings=dataclasses.replace(settings, rag_demo=True)), headers=AUTH_HEADERS)


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", plain(text)).strip()


def tiny_corpus(tmp_path, body):
    (tmp_path / "knowledge").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs" / "a.md").write_text(body)
    manifest = tmp_path / "knowledge" / "manifest.json"
    manifest.write_text(json.dumps({"documents": [{"doc_id": "doc-a", "title": "Doc A", "path": "../docs/a.md", "source_type": "project_document", "licence": "x", "approved_for_medical_use": False}]}))
    return load_corpus(manifest)


# ---------------------------------------------------------------- the diagnostic-request guard


@pytest.mark.parametrize(
    "question",
    [
        # direct requests
        "Tell me if this photo shows melanoma.", "Does this picture show basal cell carcinoma?", "Check if this mole is malignant",
        "Can you diagnose this skin image?", "Please diagnose the patient", "Diagnose my rash", "Is this lesion cancerous?",
        # identify a disease from a picture or symptoms
        "Identify the condition in this skin photo", "Can you work out what disease this rash is?", "Based on this photo, what skin cancer is it?",
        "I have an itchy red patch that keeps bleeding, what is it?", "What diagnosis fits these symptoms: fever and rash?", "What is wrong with this child?",
        # decide whether a person has a condition
        "Determine whether the patient has melanoma", "Is he suffering from psoriasis?", "Does the child have eczema?", "Does she have skin cancer?",
        "Is the person in this image sick?", "Do I have melanoma?", "Am I at risk of skin cancer?",
        # treatment and personal results
        "How do I treat actinic keratosis?", "What dose of ibuprofen should I take?", "Is my haemoglobin normal?",
    ],
)
def test_diagnostic_and_personal_requests_are_flagged(question):
    assert is_personal_medical_question(question), question


@pytest.mark.parametrize(
    "question",
    [
        "Does LUMI diagnose melanoma?", "What was the melanoma recall?", "Why is melanoma recall a concern?", "How many melanoma images were in the test set?",
        "Is the model validated for children with melanoma?", "Which skin cancers can the model predict?", "What does the model do with a photo that is not skin?",
        "How was basal cell carcinoma performance measured?", "What is the F1 score for squamous cell carcinoma?", "How many images of benign nevus were in the training split?",
        "What is Grad-CAM?", "What limitations does the skin model have?",
    ],
)
def test_project_questions_that_merely_name_a_disease_are_not_flagged(question):
    assert not is_personal_medical_question(question), question


def test_a_diagnostic_request_never_gets_a_passage_through_the_api(api):
    for question in ("Tell me if this photo shows melanoma.", "Does this picture show basal cell carcinoma?", "Identify the condition in this skin photo",
                     "Determine whether the patient has melanoma", "Do I have melanoma?"):
        body = api.post(URL, json={"question": question}).json()
        assert body["answer"] == CANNOT_ANSWER and body["result"]["sources"] == [], question
        assert body["result"]["refusal_reason"] == "personal_medical_question", question


# ---------------------------------------------------------------- relevance


@pytest.mark.parametrize(
    "question",
    ["What are the limitations of solar panels?", "Is the weather good for training the model?", "Which GPU model did you buy?",
     "What is the five-year survival rate of melanoma?", "What is the best laptop for machine learning?", "How accurate is the weather forecast?",
     "What are the limitations of electric cars?", "How is the stock market evaluated?"],
)
def test_unrelated_questions_that_share_common_words_are_refused(api, question):
    body = api.post(URL, json={"question": question}).json()
    assert body["answer"] == CANNOT_ANSWER and body["result"]["sources"] == [] and body["result"]["refusal_reason"] == "insufficient_evidence", question


def test_the_questions_rarest_word_must_appear_in_the_passage(tmp_path):
    corpus = tiny_corpus(tmp_path, "# Notes\n\nThe skin model was trained on a public dataset and its limitations are listed in the model card section for readers.\n")
    retriever = Retriever(corpus)
    assert retriever.search("What limitations does the skin model have?")  # every word of the question is in the passage
    assert retriever.search("What limitations do solar panels have?") == []  # 'solar' and 'panels' are not in any document


def test_a_word_the_documents_never_use_counts_as_the_rarest(tmp_path):
    corpus = tiny_corpus(tmp_path, "# Notes\n\nThe model was evaluated and the evaluation results for the model are described in this short section.\n")
    retriever = Retriever(corpus)
    assert retriever.search("How was the model evaluated?")
    assert retriever.search("How was the zeppelin model evaluated?") == []


def test_us_and_uk_spellings_and_un_prefixes_match():
    assert tokens("optimizer") == tokens("optimiser")
    assert "implement" in tokens("what is implemented") and "implement" in tokens("what remains unimplemented")
    assert tokens("size") == ["size"]  # the spelling rule must not touch short words


def test_a_heading_about_the_question_lifts_a_passage(tmp_path):
    body = ("# Doc\n\n## Results\n\nThe score values were reported for many different measures across the whole experiment in several tables here.\n\n"
            "## Limitations\n\nSeveral things were not done in this project and each of them is listed here for the reader to see in the text.\n")
    hits = Retriever(tiny_corpus(tmp_path, body)).search("What limitations were listed for the reader?")
    assert hits and "Limitations" in hits[0].passage.section


def test_the_skin_model_limitations_question_finds_the_limitations_section_first(retriever):
    hits = retriever.search("What limitations does the skin model have?")
    assert hits and "limitation" in hits[0].passage.section.lower() and hits[0].passage.doc_id in ("model-card", "panel-defence")
    assert "Six classes only" in hits[0].excerpt or "Not available" in hits[0].excerpt or "Melanoma" in hits[0].excerpt


def test_the_models_accuracy_is_among_the_returned_passages(retriever):
    """Known weakness, recorded honestly: the baseline's accuracy can still rank first. The model's own accuracy must be present."""
    hits = retriever.search("What was the accuracy on the held-out test set?")
    assert any("0.633" in h.excerpt or "63.30%" in h.excerpt for h in hits), [h.excerpt[:60] for h in hits]


# ---------------------------------------------------------------- passage cutting


def test_a_tiny_last_piece_of_a_long_block_is_joined_to_the_previous_piece():
    lines = "\n".join(f"- Bullet number {i} has a few words in it so that the block becomes long enough to need cutting." for i in range(1, 19))
    passages = split_markdown("# T\n\n" + lines + "\n- Last bullet.\n")
    assert all(len(p[3].split()) >= 15 for p in passages), [len(p[3].split()) for p in passages]
    assert "Last bullet." in passages[-1][3]


# ---------------------------------------------------------------- citations stay correct with the new ranking


def test_citations_still_match_the_source_files_for_many_questions(api, corpus):
    docs = {d.doc_id: d for d in corpus.documents}
    questions = ["What is Grad-CAM?", "What was the word error rate of the OCR?", "What was the learning rate?", "Was the model trained from scratch?",
                 "What limitations does the skin model have?", "What was the accuracy on the held-out test set?", "Why was epoch 7 chosen?",
                 "How many test images came from children?", "How did you avoid patient leakage?", "What was the melanoma recall?"]
    checked = 0
    for question in questions:
        body = api.post(URL, json={"question": question}).json()
        for source in body["result"]["sources"]:
            checked += 1
            doc = docs[source["doc_id"]]
            lines = (MANIFEST.parent / doc.path).read_text(encoding="utf-8").splitlines()
            first, last = (int(n) for n in source["lines"].split("-"))
            assert source["source_sha256"] == doc.sha256 and source["title"] == doc.title
            assert norm(source["excerpt"]) in norm("\n".join(lines[first - 1 : last])), (question, source["passage_id"])
    assert checked >= 15
