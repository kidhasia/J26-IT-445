# LUMI evidence package (research-ready summary)

Component IT23153318, project J26-IT-445, Multimodal AI/ML backend. Compiled 2026-10-18 from the repository (branch `feature/evidence-package`, based on develop at `fe430ab`). Every number below is copied from a file in this repository or from a command run on 2026-10-18; the source is named next to it. **Nothing here is clinical evidence.** Passing software tests show the code does what it was written to do. They say nothing about whether the medicine or the science is right.

## 0. Status in one table

| Part | State | Evidence (where to look) | Biggest limit |
|---|---|---|---|
| Secure REST API | Working | `tests/` (485 passed), `docs/SCOPE_REVIEW.md` §9 | No HTTPS, no deployment, who issues keys is undecided (C1) |
| Skin-lesion classifier | Working, first model | `docs/MODEL_CARD_skin_pad_ufes20.md` | Accuracy 0.633, macro-F1 0.543; 11 melanoma test images; adult data |
| Grad-CAM attention map | Working (skin only) | Model card §9 | Coarse (8 by 8); no clinician has judged it |
| Lab-report OCR | Working on synthetic images | `docs/OCR_EVALUATION.md`, `docs/evaluations/ocr_synthetic_results.json` | Measured on 3 clean synthetic reports only |
| Evidence-grounded Q&A | Working, smallest rule-based version, with an interface page | §5 below, `docs/evaluations/qa_results.json` | Keyword rules; author-written test questions; no users |
| Chest X-ray | **Not implemented** (placeholder) | `docs/CHEST_XRAY_PLAN.md` | No dataset approved, nothing downloaded or trained |
| Image-based medical VQA | **Not implemented** | `docs/SCOPE_REVIEW.md` FR6 | Needs a model, a dataset and an evaluation |
| Clinical validation | **Not done** | none | No clinician, no real patient, no ethics approval recorded |

## 1. Data sources, permitted use and unresolved approvals
Source: `docs/DATA_GOVERNANCE.md` §5 (log updated 2026-10-18).

| Data | Used for | Licence and source | Status |
|---|---|---|---|
| PAD-UFES-20 v1 | Skin classifier | CC BY 4.0, Mendeley Data doi:10.17632/zr7vgbcyr2.1; paper Pacheco et al., *Data in Brief* 32:106221 (2020), doi:10.1016/j.dib.2020.106221 | Downloaded 2026-10-18; checksums and integrity recorded; stored outside Git. Supervisor confirmation **pending** |
| Synthetic lab reports | OCR | Created by the project (`docs/data_cards/synthetic_lab_reports.md`) | In use; three images |
| HAM10000 | (not used) | CC BY-NC 4.0 | On hold: non-commercial clashes with the proposal's commercialisation section |
| NIH ChestX-ray14, VQA-RAD, ISIC | (not used) | Terms only partly verified (see governance §5.1, §5.4) | **Nothing downloaded** |

**Unresolved (need supervisor or ethics decision; I have not assumed any of them):**
1. Whether a public, author-de-identified CC BY dataset is acceptable without the student's own ethics application.
2. Whether an adult-dominated skin dataset is acceptable for a project framed as pediatric (only 39 of 2,298 images are from under-18s, all benign nevus).
3. Whether the ImageNet-pretrained starting weights (Apache-2.0 model card, ImageNet-1k training data) affect commercial use of the derived model.
4. Approval to present the trained model as thesis evidence.
5. Ethics approval status (TAF: "to be applied"), who the external medical reviewer is (TAF page 15 is blank), and which chest X-ray dataset is approved (C10, C11, C15, C16 in `docs/SCOPE_REVIEW.md` §8).

## 2. Skin model: method, split, measured results, limits
Source: model card, `models/skin_pad_ufes20/20261018T072750Z/metrics.json` (checkpoint not in Git).
- **Method:** EfficientNet-B0 (timm), transfer learning from ImageNet weights; six classes (ACK, BCC, MEL, NEV, SCC, SEK); 256 px, padded not cropped; 12 epochs, AdamW, weighted loss, augmentation, seed 42; the epoch (7) was chosen on the validation split.
- **Split:** after duplicate removal, 2,271 images, split **by patient** (train 1,362 / validation 454 / test 455 images; no patient in two splits, checked in code).
- **Held-out test results (evaluated once):** accuracy 0.633 (95% interval 0.584 to 0.681), macro-F1 0.543 (0.461 to 0.609), balanced accuracy 0.552, macro ROC-AUC 0.860. Baseline "always predict BCC": accuracy 0.365, macro-F1 0.089.
- **Per class (test recall, support):** ACK 0.683 (145), BCC 0.669 (166), **MEL 0.364 (11; interval 0.00 to 0.78)**, NEV 0.816 (49), **SCC 0.270 (37)**, SEK 0.511 (47). Of 11 melanomas the model found 4 and labelled 4 as nevus.
- **Serving check:** 454 of 455 test images served by the real API gave the identical class as offline evaluation; 1 was refused for exceeding the 10 MB upload limit.
- **Limits:** one dataset from one Brazilian programme, one run, one split, no external test set, six classes only, label noise possible, 6 test photos from 3 children (all benign nevus) so **no pediatric reliability claim is possible**, skin-tone coverage not analysed. Wrong on about 1 photo in 3.

## 3. Grad-CAM: method and limits
Source: model card §9, `scripts/check_gradcam_faithfulness.py`, `tests/test_gradcam.py`, `tests/test_skin_explain_api.py`.
- **Method:** Grad-CAM on the last feature map (`bn2`, 8 by 8 cells) for the predicted class, drawn on the user's photo; optional (`explain=true`).
- **Sanity checks on all 455 test images:** blanking the highlighted 20% lowered the predicted-class probability by 0.435 on average versus 0.118 for random blocks (difference +0.317, interval +0.289 to +0.347; highlighted cells mattered more in 81.5% of images). A fully random-weight copy of the model gave a map correlation of +0.05 (150 images). Two deliberate code breakages were caught by the tests.
- **What this does not show:** that the highlighted area is medically meaningful or that the prediction is right. Maps describe the model, not the lesion. **No clinician or user has judged usefulness** (the proposal's "explanation usefulness score" is not done).

## 4. OCR: CER and WER, and why they are weak evidence
Source: `docs/OCR_EVALUATION.md`, `docs/evaluations/ocr_synthetic_results.json` (byte-identical on a second run).
- **Data:** 3 synthetic report images (637 reference characters, 120 words), produced by the project's own generator.
- **Results:** LUMI pipeline CER **1.26%** (8 errors, all deleted spaces), WER **11.67%** (14 of 120 words, all moved spaces). Plain Tesseract: CER 1.10%, WER 10.00%. All 36 rows were parsed exactly (36 of 36).
- **Limit:** three clean, computer-drawn reports in one layout, the parser was written on the same layouts (in-sample), and no significance test is possible. **These numbers do not describe performance on real, photographed, skewed, noisy, scanned or PDF reports.** The comparison with plain Tesseract is slightly in favour of plain Tesseract.

## 5. Question answering: what it does, how it was checked, limits
Source: `lumi/qa/`, `POST /api/v1/ask`, the **Ask a question** page, `tests/test_qa.py`, `scripts/evaluate_qa.py`, `docs/evaluations/qa_results.json`.
- **What it is:** a rule-based reader of **one supplied analysis result** (the JSON from `/analyze` for a skin photo or a lab report). No language model, no internet, nothing stored. It is not a medical chatbot and not image question answering.
- **Supported questions:** skin: predicted class, top and per-class scores, attention-map details, model and training data, limitations, warnings. Lab: a named test's value, unit or reference range (for example "What was the reported haemoglobin value?"), which values, units or ranges were not found, which rows need review, how many rows, text-reading confidence, limitations, warnings.
- **Refusal behaviour:** anything else, and anything asking for a diagnosis, advice, treatment, risk or whether a value is normal, high or low, returns exactly: `I cannot answer this from the available evidence.` Evidence that is malformed, failed, oversized, or of another kind (for example the chest X-ray placeholder) is rejected with `invalid_evidence`.
- **Checked on 2026-10-18** (`scripts/evaluate_qa.py`, real trained model on one public test photo, real Tesseract on the three synthetic reports, real API code):

| Group | Passed |
|---|---|
| Skin questions answered correctly | 8 of 8 |
| Lab questions answered correctly | 11 of 11 |
| Diagnosis or advice requests refused | 9 of 9 |
| Not-in-evidence questions refused | 7 of 7 |
| Manipulation attempts refused | 3 of 3 |
| **Total** | **38 of 38** |

**Reworded questions, reported separately (supported questions versus questions that must be refused):**

| Set | Supported questions answered correctly | Supported but safely refused | Supported but answered wrongly | Must-refuse questions refused | Must-refuse answered unsafely |
|---|---|---|---|---|---|
| Set 1 **before** the matching fix (17 questions) | 8 of 13 | 5 | 0 | 4 of 4 | 0 |
| Set 1 after the fix (same 17; **used to guide the fix, so not independent**) | 13 of 13 | 0 | 0 | 4 of 4 | 0 |
| **Set 2** (74 new questions, written before being run) | **34 of 35 (97%)** | 1 | 0 | **39 of 39** after one fix (38 of 39 on the first run) | **0** after the fix (1 on the first run) |

(Set 1 "before" is the earlier "12 of 17" result, now split into supported and must-refuse questions; the earlier glucose gap had already been fixed by then. The five safe refusals were the five failures listed in the task.)

- **How to read that honestly:** the 38 regression questions and both reworded sets were all written by the same person who wrote the rules, so **none of this is independent validation**. Set 2 was written before it was run, which makes it a fairer guide than the 38, but its one unsafe answer ("Is the sodium within the reference range?") showed that "within/outside/above/below" were missing from the refusal list. That was fixed with a general rule and a test, so Set 2's final 39 of 39 is partly tuned to that one item. The one remaining miss ("Show all the tests that were read") is a safe refusal and was deliberately left unfixed so the result stays honest. The rules still only understand fixed vocabulary; a differently worded question can be refused even when the evidence holds the answer, and the intent is that doubt always ends in refusal, never a guess.
- **Conflicting evidence** (for example a predicted class that is not the highest score, probabilities that do not add up, a lab row that has a value but is listed as missing) is rejected with `invalid_evidence`, so the system never chooses between two statements that disagree.

- **Not done:** any test with real users, a larger or independently written question set, other languages, free-text questions about anything not in the structured result, comparison with a text-only baseline (the proposal's VQA evaluation), or a clinician rubric.
- **Trust limit:** LUMI does not verify that the supplied evidence is genuine; every answer carries an `EVIDENCE_NOT_VERIFIED` warning.

## 6. Security and software testing results
- **Full test suite, run 2026-10-18 on the final tree: 485 passed** (`.venv/bin/python -m pytest -rs`; no failures; the run was not repeated on another machine). Covers API validation, authentication, rate limiting, privacy-safe logging, upload limits, OCR parsing and evaluation, skin pipeline, Grad-CAM, the interface page, Q&A, and a repository-hygiene test that fails if data or model files become tracked.
- **Real-browser check:** `scripts/ui_smoke_test.py` in headless Chrome against a cold-started server: **97 of 97 checks passed** (pages, skin and lab workflows, Ask-a-question flows, error states, keyboard use, layout at four widths, no requests to other sites, no script errors).
- **Security properties tested:** no key, wrong key and malformed headers get 401 (also for the Q&A endpoint before any body is read); rate limit 429 with `Retry-After`; oversized bodies 413 (also for chunked uploads); wrong content type 415; invalid input 422; error messages and logs never contain file names, report text, questions, predictions or evidence (tests capture and search the log output); the interface sends a strict Content-Security-Policy and inserts server text only as plain text. Earlier live probe of the running server: `docs/SCOPE_REVIEW.md` §9 (2026-10-18 rows).
- **Not done:** HTTPS/TLS, penetration testing, load or latency measurement (no numeric targets exist, C9), dependency audit, role-based access, real key management.

## 7. What remains unimplemented, and why
| Item | Why it is not done |
|---|---|
| Chest X-ray model | The dataset approval gate (supervisor, licence confirmed from an official page) has not been passed; training an unvalidated model in the last days would add risk and no evidence. A plan exists: `docs/CHEST_XRAY_PLAN.md` |
| Image-based medical VQA / language-model reasoning | Needs a dataset, compute and an evaluation; undecided between fine-tuning and evidence prompting (C7); out of reach without approvals |
| Explanation-usefulness and answer-quality reviews | Need a clinical reviewer (C10); none confirmed |
| Real or photographed lab reports, PDFs | No permitted real documents; PDFs not supported |
| Pediatric evidence | No pediatric data beyond 39 benign-nevus photos; needs data and ethics approval |
| Integration with the team's robot, mobile and web components | The consumers of the API are unclear (C1); nothing connected |
| Numeric success targets, baselines other than majority-class and plain Tesseract | Not agreed with the supervisor (C9) |
| Thesis chapters, slides | Not in the repository yet; see `docs/SUBMISSION_PLAN.md` |

## 8. Claims you must not make
- That the skin model is accurate enough for patients, validated, or reliable for children.
- That the attention map shows where a lesion is or why the diagnosis is what it is.
- That OCR accuracy is 98.7% on lab reports in general (it is 1.26% character error on three synthetic images).
- That LUMI answers medical questions. It reads back facts from a result it was given and refuses the rest.
- That ethics approval, supervisor approval or a clinician review exists.
