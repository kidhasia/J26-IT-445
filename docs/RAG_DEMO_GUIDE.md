# LUMI retrieval demo and "Ask LUMI" helper: guide for the research panel (phase 1)

**What it is.** An **extractive retrieval prototype**. A local TF-IDF keyword search looks through LUMI's own project documents and shows the best-matching passages **word for word, with a citation for each**. **It is not a generative RAG system:** no language model writes or rewrites any text, so there is no generation step. It is **not** a clinically validated medical assistant, and it is **not** a medical chatbot.

**What it searches.** Four LUMI project documents (panel-defence record, model card, OCR evaluation, evidence package), listed in `knowledge/manifest.json`. **These are the project's own write-ups, not an approved medical knowledge base.** It cannot answer general medical questions, and nothing it returns is medical advice.

**Do not trust it to answer every question.** The search can miss relevant text, can return an incomplete or less useful passage first, and sometimes shows a passage that does not contain the fact asked for (see section 6). Always check the cited lines.

## 1. Start it
```
cd "/Users/kidhasia/Desktop/Research Stuff"
./scripts/demo_preflight.sh
./scripts/start_demo.command
```
`scripts/run_dev.sh` switches the demo on and prints `Reference search: on`. To run without it, start with `LUMI_RAG_DEMO=0 ./scripts/run_dev.sh`: the route then does not exist, `/health` has no `reference_search` entry, and all other features behave as before. Any other way of starting the server has it **off** unless `LUMI_RAG_DEMO=1` is set. `LUMI_RAG_MANIFEST` can name a different manifest (default `knowledge/manifest.json`).

## 2. Two ways to use it
- **The *Reference search* page** (left menu, tagged *Prototype*). Type a question and press **Search**.
- **The floating "Ask LUMI" helper** (round bot button, bottom-right, on every page). Click it to open a small panel without leaving the page. See section 7.

API form (the key is printed by the start script):
```
curl -s -X POST http://localhost:8000/api/v1/rag-demo -H "Authorization: Bearer local-dev-key-not-for-production" -H "Content-Type: application/json" -d '{"question": "What is Grad-CAM?"}'
```

## 3. The six demonstration questions (re-checked on 2026-10-20 against the current code)
Passage ids and line numbers change if a document is edited; the document and section should stay the same. Open the named file at the cited lines to confirm each quote.

| # | Question | Expected top source (R1) and what to look for |
|---|---|---|
| 1 | Was the model trained from scratch? | `panel-defence`, *F. Likely panel questions*, lines 66-68: "No. It started from ImageNet-pretrained weights... I have not compared it with a from-scratch model" |
| 2 | What was the word error rate of the OCR? | `ocr-evaluation`, opening summary, lines 3-5: character error rate 1.26% and **word error rate 11.67%** (plain Tesseract 1.10% and 10.00%) on three synthetic reports. R2 and R3 explain how errors are counted |
| 3 | What is Grad-CAM? | `model-card`, *9. Attention maps (Grad-CAM)*, line 95 ("What it is"). R2 is the evidence package's Grad-CAM summary, R3 the model card's "How it works" |
| 4 | How many test images came from children? | `model-card`, *4. Children*, lines 62-65: only 39 of 2,298 images are from patients under 18, all benign nevus; **6 test images from 3 children**. Read the cited lines for the 6 (the excerpt can be shortened) |
| 5 | What was the learning rate? | `panel-defence`, *A. Model and training*, lines 16-18: AdamW, **learning rate 3e-4**, weight decay 1e-4, cosine decay over 12 epochs |
| 6 | Why was epoch 7 chosen? | `panel-defence`, *A. Model and training*, line 20: validation macro-F1 peaked at 0.549 at epoch 7. R3 (`model-card`, lines 8-16) says the epoch was chosen on the validation split |

For each source the page shows document title, section, passage id, **line numbers**, file name, the first 12 characters of the file's SHA-256, the match score and how much of the question was found.

**A seventh question that also works:** "What limitations does the skin model have?" returns the model card's limitations list (lines 71-79) first. Its R2 is the **OCR** document's limitations (off-topic for the skin model) and R3 is from the panel-defence record, so say that the later results are less relevant.

## 4. Refusals (re-tested on 2026-10-20)
- **"What is the capital of France?"** returns exactly: `I cannot answer this from the available evidence.` No passage matches well enough, so nothing is shown.
- **"Do I have melanoma?"** and **"Tell me if this photo shows melanoma."** return the same sentence with the note that the demo searches project documents only. A guard refuses questions about a person's own health, diagnosis or treatment **before any search**.
- A question with fewer than two meaningful words (for example "model") is refused as too vague.
- The guard is a conservative list of word patterns, **not a medical safety classifier**. It can miss phrasings and can refuse harmless ones. Questions that only name a disease while asking about the project ("What was the melanoma recall?", "Does LUMI diagnose melanoma?") are allowed through.

## 5. What is implemented now, and what is not
| Implemented in phase 1 (tested) | Planned over the next three months (**not built**) |
|---|---|
| Local TF-IDF search over four project documents; passages keep title, section, passage id and line numbers | Search over **approved** medical or pediatric reference documents, with licence and approval records |
| Relevance filter (score, rarity-weighted word coverage, rarest-word rule) and safe refusal | Semantic (embedding) retrieval, which needs an approved model download |
| Word-for-word citations checkable against the source file, with document hashes | An answer-writing step with automatic checks that every statement is supported by a cited passage |
| Guard against personal-health and diagnosis-style requests | Pediatric versus adult labelling of sources, conflict detection between sources |
| Off by default; a broken corpus gives 503 without affecting other features | A held-out, independently written question set and **measured** retrieval quality (**none is claimed today**) |
| Interface page, floating helper, same authentication, rate limit and size limits; logs hold counts only | Combining retrieved passages with a person's own analysis result |

## 6. Known limitations and failures (say these honestly)
- **Not evaluated.** The relevance thresholds (score 0.10, at least half of the question's word weight) were fixed by hand. The tests are written by the author. They show the code behaves as written, not that retrieval is good. In the author's own small checks (not independent validation), supported questions were answered with the right passage in the top position roughly half of the time, and some correct questions are refused.
- **Known failure, kept visible as an expected failure in the tests:** *"How many images were in the test split?"* does **not** find the number 455. It still returns passages (about the baseline, the metric table and the per-class table) that do not contain the answer. Do not use this question as a demonstration, and do not treat a returned passage as proof that the question was answered.
- **Ranking can put a less useful passage first.** For *"What was the accuracy on the held-out test set?"* the baseline's 36.5% passage ranks first and the model's own accuracy (0.633) is second.
- **Vocabulary mismatches.** *"Which dataset was the skin model trained on?"* returns passages about the dataset's limits rather than the table that names PAD-UFES-20, because that table says "Data", not "dataset".
- **Refusals can be wrong in the safe direction.** Some answerable questions are refused even though the documents contain the answer (checked: "What batch size was used in training?" and "What is not implemented in LUMI?").
- **The corpus is the project's own writing.** It can be wrong or out of date, and it is not medical advice. There is no conflict handling between documents and no pediatric or adult labelling yet.
- **The index is built at start-up.** After editing a listed document, restart the server.
- No clinical validation, no independent evaluation, no real users.

## 7. The floating "Ask LUMI" helper
**What it is.** A small panel opened from a round bot button fixed at the bottom-right of every page. It does **not** write answers. It sends your question to one of two existing endpoints and shows what comes back, labelled by where it came from:

| Label in the panel | Source | Endpoint |
|---|---|---|
| **From LUMI documents** | Quoted passages with citations (document, section, passage id, lines) | `POST /api/v1/rag-demo` |
| **From your result** | Facts read back by fixed rules from a skin photo or lab-report result **you made on this page** | `POST /api/v1/ask` (the page sends the result it already holds) |
| **Guide** | Fixed help text about using the app (how to use LUMI, what LUMI can do). Not an answer from your data, and not generated | none |
| **No answer found** | The server's own refusal sentence, shown unchanged, with its note | either |

**Modes.** Two buttons at the top: **LUMI documents** and **My result**. On the Skin Analysis or Lab Reports page, once a result exists, it starts in *My result*. If no result exists, *My result* says so and links to the analysis pages; it never invents a result.

**Quick actions:** *How do I use LUMI?*, *What can LUMI do?*, *Help me understand my analysis result* (offers questions about the latest result, and never offers the "is it cancer" or "is it normal" examples), *Search LUMI research documents* (switches mode and offers three verified questions), and *What are LUMI's limitations?* (sends "What limitations does the skin model have?" to the document search).

**Behaviour.** Click the button to open; **Minimise** hides the panel but keeps the messages; **Close** clears them; **New chat** clears them; **Escape** closes the panel and returns focus to the button. Enter sends, Shift+Enter adds a line. The panel needs the same API key as the rest of the page and shows a friendly message if the key is missing or wrong, if the server is unreachable, or if document search is switched off. Reduced-motion settings stop the button's gentle bobbing. Messages exist only in the page's memory: nothing is written to browser storage, files or a database, and the server logs hold counts only (never the question, passages or answers).

**Limits.** It inherits every limit in section 6 and the rule-based answerer's limits (English keywords, fixed wording, the result is not verified). It is not an AI model and the interface does not claim it is.

## 8. Demonstration script (about 5 minutes)
1. Start with `./scripts/start_demo.command`, open http://localhost:8000/ and enter nothing else (the key is pre-filled in local development).
2. Click **Ask LUMI**. Read the welcome message aloud: what it can do and that it does not diagnose or make things up.
3. Choose **Search LUMI research documents**, then ask questions 1, 2 and 3 from section 3. Point to the labels, citations and line numbers.
4. Ask **"What is the capital of France?"** and **"Tell me if this photo shows melanoma."** to show the refusals.
5. Optional: run a skin analysis, open the helper on that page (it switches to *My result*), ask **"What was the predicted skin class?"**, then show that **"Is this cancer?"** is refused.
6. End with section 5 (implemented versus planned) and section 6 (the test-split failure).

## 9. Tests (all run on 2026-10-20)
```
.venv/bin/python -m pytest tests/test_rag.py tests/test_rag_hardening.py tests/test_chat_widget.py -rx
.venv/bin/python -m pytest -rs -rx
.venv/bin/python scripts/ui_smoke_test.py --skin-image data/raw/PAD-UFES-20/images/imgs_part_1/PAT_431_850_472.png --lab-image data/synthetic/lab_reports/syn_0001_complete.png
```
Result of the last full run: **639 passed, 1 expected failure** (the test-split question above). The real-browser smoke test, which now exercises the floating helper (opening, closing, Escape, quick actions, citations, refusals, a result question, a wrong key, and the phone layout), is reported in the milestone report with its actual result.
