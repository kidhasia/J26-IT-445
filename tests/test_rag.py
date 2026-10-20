"""Extractive retrieval demo (POST /api/v1/rag-demo): corpus loading, retrieval, citations, refusals, API, privacy.

These are software tests with questions written by the author of the retriever. They show the code behaves as written;
they are not an evaluation of retrieval quality, and the corpus is LUMI's own project documents, not medical sources.
"""

import dataclasses
import json
import logging
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumi.config import CLINICAL_BOUNDARY_NOTICE
from lumi.main import RAG_MAX_BODY_BYTES, RAG_MAX_QUESTION_CHARS, create_app
from lumi.rag import corpus as corpus_module
from lumi.rag.corpus import CorpusError, load_corpus, plain, split_markdown
from lumi.rag.retrieve import CANNOT_ANSWER, Retriever, compose_answer, is_personal_medical_question
from tests.conftest import AUTH_HEADERS, make_png

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "knowledge" / "manifest.json"
URL = "/api/v1/rag-demo"


@pytest.fixture(scope="module")
def real_corpus():
    return load_corpus(MANIFEST)


@pytest.fixture(scope="module")
def real_retriever(real_corpus):
    return Retriever(real_corpus)


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", plain(text)).strip()


# ---------------------------------------------------------------- passage extraction


def test_sections_follow_the_headings_and_code_blocks_are_not_headings():
    text = "# Title\n\nIntro words here for the document.\n\n## Part A\n\nAlpha beta gamma delta epsilon.\n\n```\n# not a heading\n```\n\n### Sub\n\nZeta eta theta iota kappa.\n"
    passages = split_markdown(text)
    sections = [p[0] for p in passages]
    assert "Title > Part A" in sections and "Title > Part A > Sub" in sections
    assert not any("not a heading" in s for s in sections)


def test_line_numbers_point_at_the_passage_text():
    text = "# T\n\nOne two three four five six seven.\nEight nine ten eleven twelve.\n\n## B\n\nThirteen fourteen fifteen sixteen.\n"
    lines = text.splitlines()
    for section, first, last, body in split_markdown(text):
        assert body == "\n".join(lines[first - 1 : last])


def test_a_very_long_line_is_cut_at_sentence_ends():
    sentence = "The quick brown fox jumps over the lazy dog near the river bank today. "
    passages = split_markdown("# T\n\n" + sentence * 40)
    assert len(passages) > 1
    assert all(len(p[3].split()) <= corpus_module.MAX_WORDS for p in passages)


def test_markdown_decoration_is_removed_but_words_and_numbers_stay():
    assert plain("**Accuracy** is `63.30%` ([see](http://x.y))") == "Accuracy is 63.30% (see)"


# ---------------------------------------------------------------- loading the real corpus


def test_the_real_corpus_loads_with_full_metadata(real_corpus):
    assert [d.doc_id for d in real_corpus.documents] == ["panel-defence", "model-card", "ocr-evaluation", "evidence-package"]
    ids = [p.passage_id for p in real_corpus.passages]
    assert len(ids) == len(set(ids)) > 50
    for doc in real_corpus.documents:
        assert doc.approved_for_medical_use is False and doc.source_type == "project_document" and doc.licence == "project-owned"
        assert len(doc.sha256) == 64


def test_every_passage_is_a_real_piece_of_its_source_file(real_corpus):
    sources = {}
    for doc in real_corpus.documents:
        sources[doc.doc_id] = (MANIFEST.parent / doc.path).read_text(encoding="utf-8").splitlines()
    for p in real_corpus.passages:
        lines = sources[p.doc_id]
        assert 1 <= p.line_start <= p.line_end <= len(lines)
        assert norm(p.text) in norm("\n".join(lines[p.line_start - 1 : p.line_end])), p.passage_id


# ---------------------------------------------------------------- malformed or unsafe manifests


def write_manifest(tmp_path, documents, extra_files=None):
    (tmp_path / "knowledge").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs").mkdir(exist_ok=True)
    for name, content in (extra_files or {"a.md": "# A\n\nAccording to the laboratory notebook, the flarnax count was forty two on Tuesday morning.\n"}).items():
        (tmp_path / "docs" / name).write_bytes(content if isinstance(content, bytes) else content.encode())
    path = tmp_path / "knowledge" / "manifest.json"
    path.write_text(json.dumps({"documents": documents}))
    return path


def good_doc(**changes):
    doc = {"doc_id": "doc-a", "title": "Doc A", "path": "../docs/a.md", "source_type": "project_document", "licence": "project-owned", "approved_for_medical_use": False}
    doc.update(changes)
    return doc


def test_a_good_manifest_loads(tmp_path):
    assert len(load_corpus(write_manifest(tmp_path, [good_doc()])).passages) == 1


@pytest.mark.parametrize(
    "document",
    [
        {k: v for k, v in good_doc().items() if k != "licence"},
        {k: v for k, v in good_doc().items() if k != "approved_for_medical_use"},
        good_doc(doc_id="Bad ID!"),
        good_doc(source_type="wikipedia"),
        good_doc(source_type="approved_reference"),  # needs an approved_by record
        good_doc(approved_for_medical_use="yes"),
        good_doc(title=""),
        good_doc(path="../docs/missing.md"),
        good_doc(path="../docs/a.txt"),
        good_doc(path="../../outside.md"),
        good_doc(path="/etc/hosts"),
        "not an object",
    ],
)
def test_malformed_or_unsafe_manifest_entries_are_rejected(tmp_path, document):
    manifest = write_manifest(tmp_path, [document], {"a.md": "# A\n\nSome words here.\n", "a.txt": "x"})
    (tmp_path.parent / "outside.md").write_text("# O\n\nOutside words here for the test.\n")
    with pytest.raises(CorpusError):
        load_corpus(manifest)


def test_other_manifest_problems_are_rejected(tmp_path):
    with pytest.raises(CorpusError):
        load_corpus(tmp_path / "nothing.json")
    bad = tmp_path / "knowledge"
    bad.mkdir()
    for content in ("{not json", "[]", '{"documents": []}', '{"documents": "x"}'):
        (bad / "manifest.json").write_text(content)
        with pytest.raises(CorpusError):
            load_corpus(bad / "manifest.json")
    with pytest.raises(CorpusError):  # the same id twice
        load_corpus(write_manifest(tmp_path / "t1", [good_doc(), good_doc()]))
    with pytest.raises(CorpusError):  # not UTF-8
        load_corpus(write_manifest(tmp_path / "t2", [good_doc()], {"a.md": b"\xff\xfe\x00bad"}))
    with pytest.raises(CorpusError):  # nothing to extract
        load_corpus(write_manifest(tmp_path / "t3", [good_doc()], {"a.md": "\n\n"}))


def test_an_oversized_file_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus_module, "MAX_FILE_BYTES", 10)
    with pytest.raises(CorpusError):
        load_corpus(write_manifest(tmp_path, [good_doc()]))


def test_an_approved_reference_needs_an_approval_record(tmp_path):
    manifest = write_manifest(tmp_path, [good_doc(source_type="approved_reference", approved_by="Dr Example, 2026-10-20")])
    assert load_corpus(manifest).documents[0].source_type == "approved_reference"


# ---------------------------------------------------------------- retrieval


@pytest.mark.parametrize(
    "question, doc_id, expected_text",
    [
        ("What was the melanoma recall?", "panel-defence", "recall 36.4%"),
        ("Was the model trained from scratch?", "panel-defence", "started from ImageNet-pretrained weights"),
        ("What is the character error rate of the OCR?", "ocr-evaluation", "1.26%"),
        ("How did you avoid patient leakage?", "panel-defence", "stratified by diagnosis"),
        ("What is Grad-CAM?", "model-card", "Grad-CAM weights each channel"),
    ],
)
def test_relevant_questions_retrieve_the_expected_passage(real_retriever, question, doc_id, expected_text):
    hits = real_retriever.search(question)
    assert hits, question
    assert any(expected_text in plain(h.passage.text) or expected_text in h.excerpt for h in hits if doc_id in (None, h.passage.doc_id)), [h.excerpt[:80] for h in hits]


@pytest.mark.xfail(strict=True, reason="Known miss, kept visible on purpose: the number 455 sits in a table row and in a heading, which the keyword "
                   "search ranks below other passages for this wording. If retrieval improves this test will start passing and should be updated.")
def test_known_retrieval_miss_the_test_split_size(real_retriever):
    hits = real_retriever.search("How many images were in the test split?")
    assert any("455" in h.excerpt for h in hits)


@pytest.mark.parametrize(
    "question",
    ["What is the capital of France?", "What is the weather today?", "Who won the football world cup?", "Tell me a joke",
     "model", "a b c", "?????", "", "   ", "How do I bake sourdough bread?"],
)
def test_irrelevant_or_empty_questions_find_nothing(real_retriever, question):
    assert real_retriever.search(question) == []


@pytest.mark.parametrize(
    "question",
    ["Do I have melanoma?", "Should I worry about my mole?", "Is this cancer?", "What treatment does my child need?",
     "What medicine should I take for it?", "Please diagnose me", "Is my result normal?", "Can I take ibuprofen?"],
)
def test_questions_about_a_persons_own_health_are_flagged(question):
    assert is_personal_medical_question(question)


@pytest.mark.parametrize(
    "question",
    ["What limitations does the skin model have?", "Does LUMI diagnose melanoma?", "Is the model validated for children?",
     "What is melanoma recall?", "How was the model evaluated?"],
)
def test_questions_about_the_project_are_not_flagged(question):
    assert not is_personal_medical_question(question)


def test_search_is_deterministic(real_retriever):
    first = [(h.passage.passage_id, h.score) for h in real_retriever.search("What limitations does the skin model have?")]
    assert first and first == [(h.passage.passage_id, h.score) for h in real_retriever.search("What limitations does the skin model have?")]


def test_answers_come_from_the_documents_not_from_fixed_text(tmp_path):
    """A brand-new document with a made-up fact is answered from, and changing the file changes the answer."""
    manifest = write_manifest(tmp_path, [good_doc()], {"a.md": "# Notes\n\nAccording to the laboratory notebook, the flarnax count was forty two on Tuesday morning.\n"})
    first = Retriever(load_corpus(manifest)).search("What was the flarnax count?")
    assert "forty two" in first[0].excerpt
    (tmp_path / "docs" / "a.md").write_text("# Notes\n\nAccording to the laboratory notebook, the flarnax count was seventeen on Tuesday morning.\n")
    second = Retriever(load_corpus(manifest)).search("What was the flarnax count?")
    assert "seventeen" in second[0].excerpt and "forty" not in second[0].excerpt
    assert Retriever(load_corpus(manifest)).search("What is the capital of France?") == []


def test_the_answer_text_is_only_the_lead_in_plus_the_cited_excerpts(real_retriever):
    hits = real_retriever.search("What limitations does the skin model have?")
    answer = compose_answer(hits)
    lines = answer.split("\n")
    assert lines[0].startswith("From LUMI project documents") and "not medical advice" in lines[0]
    assert "\n".join(lines[1:]) == "\n".join(f"[R{i}] {h.excerpt}" for i, h in enumerate(hits, start=1))


# ---------------------------------------------------------------- the API


@pytest.fixture
def rag_settings(settings):
    return dataclasses.replace(settings, rag_demo=True)


@pytest.fixture
def api(rag_settings):
    return TestClient(create_app(settings=rag_settings), headers=AUTH_HEADERS)


def post(client, question="Was the model trained from scratch?", **kwargs):
    return client.post(URL, json={"question": question}, **kwargs)


def test_a_project_question_returns_cited_passages_in_the_standard_envelope(api):
    response = post(api, "What limitations does the skin model have?")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"request_id", "input_type", "result", "confidence", "answer", "explanation", "xai_reference", "warnings", "clinical_boundary_notice", "error"}
    assert body["input_type"] is None and body["error"] is None and body["clinical_boundary_notice"] == CLINICAL_BOUNDARY_NOTICE
    result = body["result"]
    assert result["mode"] == "extractive_retrieval_demo" and result["answerable"] is True and result["refusal_reason"] is None
    assert 1 <= len(result["sources"]) <= 3
    codes = " ".join(w.split(":")[0] for w in body["warnings"])
    assert "PROJECT_DOCUMENTS_ONLY" in codes and "EXTRACTIVE_PROTOTYPE" in codes


def test_every_citation_points_at_the_exact_source_text(api, real_corpus):
    docs = {d.doc_id: d for d in real_corpus.documents}
    for question in ("What limitations does the skin model have?", "What was the melanoma recall?", "What is the character error rate of the OCR?", "What is Grad-CAM?"):
        body = post(api, question).json()
        assert body["result"]["answerable"], question
        for number, source in enumerate(body["result"]["sources"], start=1):
            assert source["citation"] == f"R{number}" and f"[R{number}] " in body["answer"]
            doc = docs[source["doc_id"]]
            path = MANIFEST.parent / doc.path
            assert source["source_sha256"] == doc.sha256 and source["title"] == doc.title and source["path"] == doc.path
            first, last = (int(n) for n in source["lines"].split("-"))
            lines = path.read_text(encoding="utf-8").splitlines()
            assert norm(source["excerpt"]).replace(" …", "") in norm("\n".join(lines[first - 1 : last])), (question, source["passage_id"])
            assert source["approved_for_medical_use"] is False and source["source_type"] == "project_document"
            assert source["excerpt"] in body["answer"]


@pytest.mark.parametrize("question, reason", [
    ("What is the capital of France?", "insufficient_evidence"),
    ("Tell me a joke", "insufficient_evidence"),
    ("Do I have melanoma?", "personal_medical_question"),
    ("What treatment does my child need?", "personal_medical_question"),
])
def test_refusals_use_the_exact_sentence_and_give_no_sources(api, question, reason):
    body = post(api, question).json()
    assert body["answer"] == CANNOT_ANSWER == "I cannot answer this from the available evidence."
    assert body["result"]["answerable"] is False and body["result"]["refusal_reason"] == reason and body["result"]["sources"] == []
    assert body["explanation"] and "PROJECT_DOCUMENTS_ONLY" in " ".join(body["warnings"])


def test_authentication_is_required(rag_settings):
    anonymous = TestClient(create_app(settings=rag_settings))
    assert post(anonymous).status_code == 401
    assert anonymous.post(URL, content=b"not json", headers={"Content-Type": "application/json"}).status_code == 401
    assert post(anonymous, headers={"Authorization": "Bearer wrong-key-0000000000"}).status_code == 401


def test_the_endpoint_is_rate_limited(rag_settings):
    client = TestClient(create_app(settings=dataclasses.replace(rag_settings, rate_limit_per_minute=2)), headers=AUTH_HEADERS)
    codes = [post(client).status_code for _ in range(4)]
    assert codes[:2] == [200, 200] and 429 in codes[2:]


@pytest.mark.parametrize(
    "payload, code, field",
    [
        ({}, "missing_field", "question"),
        ({"question": 5}, "invalid_field", "question"),
        ({"question": "   "}, "invalid_field", "question"),
        ({"question": "x" * (RAG_MAX_QUESTION_CHARS + 1)}, "invalid_field", "question"),
        ({"question": "hi\x00there"}, "invalid_field", "question"),
        ({"question": "hello there", "extra": 1}, "invalid_field", "extra"),
        (["a", "list"], "invalid_field", "body"),
    ],
)
def test_invalid_input_is_rejected(api, payload, code, field):
    response = api.post(URL, json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == code and response.json()["error"]["field"] == field and response.json()["answer"] is None


def test_malformed_json_and_wrong_content_type_are_rejected(api):
    bad = api.post(URL, content=b"{oops", headers={"Content-Type": "application/json"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_field"
    wrong = api.post(URL, content=b"question=hi", headers={"Content-Type": "text/plain"})
    assert wrong.status_code == 415 and wrong.json()["error"]["code"] == "unsupported_media_type"


def test_oversized_bodies_are_rejected(api):
    big = api.post(URL, json={"question": "hi", "pad": "x" * (RAG_MAX_BODY_BYTES + 10)})
    assert big.status_code == 413 and big.json()["error"]["code"] == "file_too_large"
    chunked = api.post(URL, content=(b"x" * 500 for _ in range(30)), headers={"Content-Type": "application/json"})
    assert chunked.status_code == 413


def test_questions_passages_and_answers_are_not_logged(api, caplog):
    with caplog.at_level(logging.DEBUG):
        assert post(api, "What was the ZZUNIQUEWORD melanoma recall?").status_code == 200
        post(api, "Do I have ZZUNIQUEWORD melanoma?")
        post(api, "ZZUNIQUEWORD", )
    logged = caplog.text
    assert '"event": "rag_demo"' in logged
    for forbidden in ("ZZUNIQUEWORD", "recall 36.4", "ImageNet", "melanoma"):
        assert forbidden not in logged


def test_the_endpoint_appears_in_openapi_and_health_reports_the_demo(api):
    assert URL in api.get("/openapi.json").json()["paths"]
    assert api.get("/health").json()["reference_search"] == {"status": "ready", "documents": 4, "passages": pytest.approx(api.get("/health").json()["reference_search"]["passages"])}


# ---------------------------------------------------------------- broken corpus and the switch being off


def test_a_broken_corpus_gives_503_and_leaves_everything_else_working(rag_settings, tmp_path):
    broken = tmp_path / "knowledge"
    broken.mkdir()
    (broken / "manifest.json").write_text("{not json")
    settings = dataclasses.replace(rag_settings, rag_manifest=str(broken / "manifest.json"))
    client = TestClient(create_app(settings=settings), headers=AUTH_HEADERS)
    response = post(client)
    assert response.status_code == 503 and response.json()["error"]["code"] == "reference_unavailable" and response.json()["answer"] is None
    assert client.get("/health").json()["reference_search"]["status"] == "unavailable"
    other = client.post("/api/v1/analyze", data={"input_type": "chest_xray"}, files={"file": ("x.png", make_png(), "image/png")})
    assert other.status_code == 200  # existing endpoints are unaffected


def test_when_switched_off_the_route_and_health_key_do_not_exist(settings):
    off = TestClient(create_app(settings=settings), headers=AUTH_HEADERS)
    assert post(off).status_code == 404
    assert "reference_search" not in off.get("/health").json()
    assert URL not in off.get("/openapi.json").json()["paths"]


def test_the_switch_comes_from_the_environment():
    from lumi.config import Settings

    assert Settings.from_env({}).rag_demo is False
    assert Settings.from_env({"LUMI_RAG_DEMO": "1"}).rag_demo is True
    assert Settings.from_env({"LUMI_RAG_DEMO": "true"}).rag_demo is False  # only "1" switches it on


# ---------------------------------------------------------------- existing endpoints are unchanged by the demo


def test_ask_and_analyze_behave_the_same_with_the_demo_on_or_off(settings):
    evidence = {
        "input_type": "lab_report", "confidence": None, "warnings": [], "clinical_boundary_notice": CLINICAL_BOUNDARY_NOTICE, "error": None,
        "result": {"status": "completed", "pipeline": "lab_report_ocr", "mean_ocr_confidence": 90.0, "fields_needing_review": 0,
                   "fields": [{"test_name": "Sodium", "value": "139", "unit": "mmol/L", "reference_range": "135 - 145", "missing_fields": [], "needs_review": False, "line_number": 1, "ocr_confidence": 90.0}]},
    }
    results = []
    for rag in (False, True):
        client = TestClient(create_app(settings=dataclasses.replace(settings, rag_demo=rag)), headers=AUTH_HEADERS)
        ask = client.post("/api/v1/ask", json={"question": "What was the sodium value?", "evidence": evidence}).json()
        refused = client.post("/api/v1/ask", json={"question": "Is this normal?", "evidence": evidence}).json()
        xray = client.post("/api/v1/analyze", data={"input_type": "chest_xray", "question": "What does this show?"}, files={"file": ("x.png", make_png(), "image/png")}).json()
        results.append((ask["answer"], refused["answer"], xray["answer"], xray["warnings"]))
    assert results[0] == results[1]
    assert "139" in results[0][0] and results[0][1] == CANNOT_ANSWER and results[0][2] is None
