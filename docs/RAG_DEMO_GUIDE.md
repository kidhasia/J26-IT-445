# LUMI retrieval demo: guide for the research panel (phase 1)

**What it is:** an **extractive retrieval prototype**. It searches LUMI's own project documents with a local TF-IDF keyword search and shows the best-matching passages **word for word, with a citation for each**. **It is not a generative RAG system:** no language model writes or rewrites any text, so there is no generation step to hallucinate. It is not a medical chatbot, and its sources are **not** an approved medical knowledge base.

## 1. Start it
```
cd "/Users/kidhasia/Desktop/Research Stuff"
./scripts/start_demo.command
```
`scripts/run_dev.sh` switches the demo on (it prints `Reference search: on`). To run without it, start with `LUMI_RAG_DEMO=0 ./scripts/run_dev.sh`; the route then does not exist and everything else behaves exactly as before. Any other way of starting the server has it **off** unless `LUMI_RAG_DEMO=1` is set. `LUMI_RAG_MANIFEST` can point at a different manifest (default `knowledge/manifest.json`).

## 2. Open it
Browser: http://localhost:8000/ then **Reference search** in the left menu (tagged *Prototype*). API form (key is printed by the start script):
```
curl -s -X POST http://localhost:8000/api/v1/rag-demo -H "Authorization: Bearer local-dev-key-not-for-production" -H "Content-Type: application/json" -d '{"question": "Was the model trained from scratch?"}'
```

## 3. Three questions grounded in real project documents
Checked on 2026-10-20 against the documents as they are now. Passage ids and line numbers change if a document is edited, but the source document and section should stay the same.

| Question | Expected top source (what you should see) |
|---|---|
| Was the model trained from scratch? | **R1:** `panel-defence`, section *F. Likely panel questions* (lines 66-68), the answer that it started from ImageNet-pretrained weights and was **not** compared with a from-scratch model. Further passages come from *A. Model and training* |
| What was the character error rate of the lab-report reading? | **R1:** `ocr-evaluation`, the opening summary (lines 3-5): character error rate 1.26% and word error rate 11.67% on three synthetic reports, versus plain Tesseract |
| How did you avoid patient leakage? | **R1:** `panel-defence`, section *F. Likely panel questions* (lines 69-71): splitting by patient, stratified, with a leakage check |

For each source the page shows the document title, section, passage id, **line numbers**, file path, the first 12 characters of the file's SHA-256, the match score and the share of your question words found. Open the named file at those lines to confirm the quote.

## 4. Insufficient evidence and unsafe questions
- **"What is the capital of France?"** returns exactly: `I cannot answer this from the available evidence.` No passage matches well enough, so nothing is shown.
- **"Do I have melanoma?"** (any question about your own health, diagnosis or treatment) returns the same sentence plus the note that the demo searches project documents only. These are refused *before* any search.
- A single vague word such as "model" is also refused: a question needs at least two meaningful words.

## 5. What is implemented now, and what is not
| Implemented in phase 1 (tested) | Planned over the next three months (**not built**) |
|---|---|
| Local TF-IDF search over four project documents; passages with title, section, passage id and line numbers | Search over **approved** medical or pediatric reference documents, with licence and approval records |
| Relevance threshold and safe refusal; refusal of personal-medical questions | Semantic (embedding) retrieval, which needs an approved model download |
| Word-for-word citations that can be checked against the source file; document hashes | An answer-writing step with automatic checks that every statement is supported by a cited passage |
| Switch off by default; broken corpus gives 503 without affecting other features | Pediatric versus adult labelling of sources, conflict detection between sources |
| Privacy-safe logs (counts only), same authentication, rate limit and size limits | A held-out, independently written question set and measured retrieval quality (**no accuracy is claimed today**) |
| Interface page and API tests (see `tests/test_rag.py`) | Combining retrieved passages with a patient's own analysis result |

## 6. Known limitations (say these honestly)
- **Not evaluated.** The relevance thresholds (score 0.10, at least half of the question's words) were chosen by hand after trying about a dozen questions. The tests are by the author and show the code behaves as written, not that retrieval is good.
- **Keyword matching only.** Different wording can miss: "How many images were in the test split?" does not find the number 455 (recorded as an expected failure in the tests).
- **Broad questions return mixed passages.** For "What limitations does the skin model have?" the best matches come from several documents and are not always the most complete list. Very short fragments are not returned.
- **The corpus is the project's own writing.** It can be wrong or out of date, it is not medical advice, and it cannot answer general medical questions.
- **No conflict handling** between documents, and no pediatric or adult labelling yet.
- **The index is built at start-up.** After editing a document, restart the server.
- No clinical validation, no independent evaluation, no real users.

## 7. Tests
```
.venv/bin/python -m pytest tests/test_rag.py -rx
.venv/bin/python -m pytest -rs
.venv/bin/python scripts/ui_smoke_test.py --skin-image <a PNG> --lab-image data/synthetic/lab_reports/syn_0001_complete.png
```
