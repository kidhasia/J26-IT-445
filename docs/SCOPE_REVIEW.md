# LUMI — Scope Review and Traceability (IT23153318, J26-IT-445)

Sources:
- **TAF**: `TAF-J26-IT-445.pdf` (Topic Assessment Form V2.2, accepted by panel 07/07/2026)
- **PROP**: `J26-IT-445 - IT23153318.pdf` (individual Project Proposal Report)

Created: 2026-10-16. No code exists yet, so every implementation status is **Not started**.

---

## 1. Responsibilities assigned to IT23153318

From TAF §9 (sub-objective and tasks) and PROP §2.2 / Table 16:

| # | Responsibility | Source |
|---|---|---|
| A1 | Collect and preprocess skin, X-ray and lab report datasets (plus VQA pairs) | TAF §9; PROP SO1 |
| A2 | Image-analysis pipelines for skin lesion and chest X-ray | PROP SO2 (TAF: "Fine-tune ViT ...") |
| A3 | OCR pipeline for lab report text and field extraction | TAF §9; PROP SO3 |
| A4 | Multimodal VQA / reasoning layer (evidence + question → answer) | TAF §9 ("Fine-tune ViT and LLM models for medical VQA"); PROP SO4 |
| A5 | Explainable AI output layer | TAF §9; PROP SO5 |
| A6 | Secure REST API used by all platforms | TAF §9; PROP SO6 |
| A7 | API contract definition and integration testing (**shared** with client owners) | PROP Table 16 |
| A8 | Overall system integration and final acceptance (**shared**, whole team) | PROP Table 16 |

**Not mine** (PROP Table 16 and TAF §9): client UIs, robot hardware, games, outbreak risk modelling, notification service, therapeutic game engine, and the team-owned database.

## 2. Inputs and outputs

**Inputs** (PROP §4, App. A): a file (skin photo, chest X-ray image, or lab report PDF/image), a declared `input_type`, a natural-language question, and optional metadata.

**Output envelope** (PROP App. A), the same for every input type:
`request_id`, `input_type`, `result`, `confidence`, `answer`, `explanation`, `xai_reference`, `warnings`, `clinical_boundary_notice`.
When validation fails, the same envelope comes back with an `error` object in place of `result` and `answer`.

## 3. Dependencies on other team components

| Component / member | What they need from LUMI | What LUMI needs from them |
|---|---|---|
| IoT robot — IT23207622 | Report image + transcribed question → child-friendly answer | Agreement on where OCR runs and who turns speech into text; payload size limits |
| Mobile / web — IT23256682 (per PROP Fig. 3–4) | Image or report + typed question → structured JSON | Confirmation that they actually consume LUMI (see C1) |
| Outbreak system — IT23415768 (per PROP §4.1) | "Aggregated, de-identified signals" | Unclear (see C3) |
| Shared backend/DB (team-owned; IT23207622 builds a "backend/database system") | — | Where audit logs live; who issues auth tokens |

## 4. Proposed datasets (as written; nothing has been obtained yet)

| Modality | Public source | Local source (needs ethics approval) |
|---|---|---|
| Skin | HAM10000, ISIC | De-identified clinical photos from local doctors |
| Chest X-ray | NIH ChestX-ray14 / "ChestX-ray family" | De-identified hospital scans |
| Lab reports | None public. Synthetic "controlled sample reports" for OCR ground truth | De-identified reports under consent |
| VQA | VQA-Med (ImageCLEF) | — |
| Test questions | Project-written question set, by question type | — |

## 5. Evaluation metrics (PROP §3.4, Table 6)

Accuracy and balanced accuracy; per-class precision, recall and F1; ROC-AUC; OCR CER/WER; VQA exact match, F1 and rubric scores; end-to-end latency; API success rate; explanation-usefulness rubric score.
Baselines (PROP Table 5): a single-modality classifier, default-config OCR, VQA-Med, a text-only QA workflow, and the same responses with explanations suppressed.
**No numeric targets are given anywhere** (see C9).

## 6. Ethical and security constraints

- The system supports clinicians and does not replace them. A clinical boundary notice goes on every applicable response (FR10; TAF p.10).
- **Ethics (IRB/ERB) approval: "To be applied"** (TAF p.10). Neither document records an approval.
- Parental/guardian consent is mandatory for any child data. Informed consent is required from clinical partners.
- No PII is used for development or evaluation without formal approval. Data is anonymised and access-controlled. Licensed data stays in the approved environment (PROP §3.2).
- Security: authentication, HTTPS/TLS, rate limiting (PROP §4). The TAF also lists JWT/OAuth 2.0 and RBAC.
- HIPAA/GDPR "principles applied" (TAF p.10).
- Panel condition (TAF p.16): **"Gather & validate the required data from appropriate sources."**

---

## 7. Traceability table

Status values: Not started / In progress / Done (with evidence) / Blocked.
Rows marked "Not started" list *proposed* module paths. Other rows list the real files.
"Tests pass" means on the assistant's run in the project `.venv` (Python 3.12.15); the student's own confirming run is recorded in §9.

| ID | Requirement | Implementation module | Test / evidence | Status | Open question |
|---|---|---|---|---|---|
| SO1 | Collect and preprocess data; fixed, recorded train/val/test splits | `lumi/data_inspect/`, `lumi/ml/skin_data.py` (patient-level split + duplicate rule), `lumi/ml/train_skin.py` | PAD-UFES-20 downloaded (sizes match the official listing, zips intact) and inspected with `lumi.data_inspect`; split counts and duplicate handling saved in each run's `config.json`; leakage check in code; `tests/test_skin_ml.py`. Splits are reproducible from the seed (not saved as a file) | **In progress: done for skin only.** No chest X-ray, VQA or real lab-report data obtained | Supervisor approval of the dataset (PENDING); chest X-ray dataset choice |
| FR1 | Accept skin and chest X-ray images through the API | `lumi/main.py`, `lumi/validation.py` | `tests/test_validation.py`, `tests/test_api.py`, `tests/test_skin_api.py`: valid PNG/JPEG accepted (RGB, RGBA, greyscale, odd shapes); empty, oversize, wrong type, mismatched type and corrupt files rejected. Measured: 10 of 2,298 real dataset PNGs exceed the 10 MB limit and are refused with 413 | Done for intake | Accepted formats (DICOM?) and the 10 MB limit are placeholders; clients may need to compress large photos |
| FR2 | Preprocess images (resize, normalise, colour) | `lumi/ml/skin_model.py` (`letterbox`, `to_tensor`) | `tests/test_skin_ml.py`: aspect ratio kept, padding neutral, all colour modes handled. Same code is used in training and in the API | Done for skin; **not started for chest X-ray** | — |
| FR3 / SO2 | Image analysis returns class + confidence | `lumi/pipelines/skin/pipeline.py`, `lumi/ml/train_skin.py`, `lumi/pipelines/unavailable.py`; chest X-ray: none | Real run `20261018T072750Z` (EfficientNet-B0, PAD-UFES-20): test accuracy 0.633 (95% interval 0.584 to 0.681), macro-F1 0.543 (0.461 to 0.609), balanced accuracy 0.552, macro ROC-AUC 0.860 on 455 held-out images, baseline macro-F1 0.089; per-class and confusion matrix in `docs/MODEL_CARD_skin_pad_ufes20.md`. API reproduced the offline predicted class for 454 of 454 served test images (1 refused: file too large). 26 API tests with an untrained tiny model. No checkpoint configured -> `503 model_unavailable` | **Skin: In progress (first model working, weak).** Melanoma recall 0.36 on only 11 cases (interval 0 to 0.78); SCC F1 0.26. **No pediatric evidence:** 39 of 2,298 images are from under-18s, all benign nevus (test: 6 images, 3 children). Chest X-ray: **Not started.** No ROC/F1 comparison against a published baseline yet | Is accuracy 0.63 acceptable (C9: no numeric targets)? Is an adult-dominated dataset acceptable for a pediatric project (C5)? Which chest X-ray dataset is approved? |
| FR4 / SO3 | OCR on lab reports → text + parsed fields | `lumi/pipelines/ocr/engine.py` (local Tesseract 5.5.3 via stdin/stdout, no temp files), `parser.py`, `pipeline.py`; `lumi/eval/synthetic_lab_reports.py` | `tests/test_ocr_parser.py`, `test_ocr_engine.py`, `test_ocr_api.py` (42 tests). On the default 6-row synthetic report (PNG and JPEG), every parsed field equals the ground truth. Missing value/range is flagged, not guessed | **In progress.** Done: PNG/JPEG images, raw text kept, per-line confidence, needs_review flags, evidence line numbers. **Not done:** PDF reports (still mock + warning); phone-photo preprocessing (deskew, contrast); **CER/WER evaluation and the default-Tesseract baseline (EVAL)**; real or de-identified reports (needs ethics approval, C11) | Which report layouts and fields? Does the robot send photos or text (C4)? The 60/100 review-confidence threshold is an engineering placeholder |
| FR5 | Accept natural-language questions | `lumi/main.py` (`_clean_question`) | `tests/test_api.py`: blank → treated as absent; >1000 chars → 422. Questions are accepted but answered by nothing yet (`QUESTION_NOT_ANSWERED` warning) | In progress: intake only | Languages: English only, or Sinhala/Tamil too? Neither document says |
| FR6 / SO4 | Combine evidence + question → context-aware answer | `lumi/reasoning/` | VQA-Med EM/F1 where compatible; rubric scores per question type; comparison with the text-only baseline | Not started | Fine-tune an LLM (TAF) or use a pre-trained model with evidence prompting (C7)? Local model or external API (privacy, C11)? |
| FR7 / SO5 | Explainable output (saliency map / evidence span) | `lumi/xai/` (not written); OCR evidence lines exist in `lumi/pipelines/ocr/` | OCR fields return `line_number` and `source_text`. **No Grad-CAM yet:** the skin response says explicitly that no heatmap is available | **Not started for images; partial for lab reports** | Who are the reviewers (C10)? Are Grad-CAM + evidence spans enough, or are LIME/SHAP required (C8)? |
| FR8 / SO6 | Secure REST API used by the clients | `lumi/main.py`, `lumi/auth.py`, `lumi/ratelimit.py` | `tests/test_security.py`: no token → 401; bad token → 401; no keys configured → 401 (fail closed); rate limit → 429; oversized body → 413 | In progress: API keys + rate limit done; **HTTPS/TLS, deployment and real client integration not done** | Who issues tokens: LUMI or the team backend? Which clients really call it (C1)? |
| FR9 | Distinct, structured success / validation-error / failure responses | `lumi/schemas.py` (`AnalyzeResponse`, `ErrorCode`), `lumi/main.py` | `tests/test_api.py`, `test_ocr_api.py`: same envelope keys on 200/400/401/413/415/422/429/500/503 | Done for the prototype; contract not yet agreed with client owners | Need an agreed list of error codes with client owners |
| FR10 | Clinical boundary notice on every applicable response | `lumi/config.py` (`CLINICAL_BOUNDARY_NOTICE`), `lumi/service.py` | Tests assert the notice on success and error responses. The OCR pipeline also carries a reference-range note: ranges are lab- and age-specific, and LUMI does not judge normality | In progress: wording is a placeholder pending supervisor approval | Exact wording needs supervisor approval. Include it on error responses too? |
| FR11 | Logs good enough for debugging/evaluation, with no unnecessary PII | `lumi/logging_config.py` | `tests/test_security.py`, `test_ocr_api.py`: logs never contain question text, filenames, metadata values, API keys or OCR text/values; live server log checked manually (0 matches) | Done for current pipelines | Where do logs go (local file vs team DB)? Retention period? |
| NFR-Perf | Latency "fast enough for bedside interaction" | `scripts/bench_latency.py` | Per-pipeline and end-to-end latency recorded on every run | Not started | **No numeric target** (C9) |
| NFR-Rel | Consistent processing; invalid requests rejected safely | `tests/test_reliability.py` | Success/error rate over repeated runs | Not started | **No numeric target** (C9) |
| NFR-Sec | Data protected in transit; controlled access | `lumi/api/auth.py`, deployment config | Unauthenticated access verified as rejected | Not started | Where is it deployed, and who manages TLS? |
| NFR-Priv | Keep only necessary data; de-identified data for research | Data-handling doc | Review against the project ethics position | Not started | Blocked on the ethics approval status |
| NFR-Scale | Several clients share one service | `scripts/load_test.py` | Concurrent-request test within prototype scope | Not started | Expected number of concurrent users? |
| NFR-Maint | Vision, OCR, VQA, XAI and API modules independently replaceable | `lumi/pipelines/base.py` (`Pipeline` protocol), `lumi/service.py` router; OCR engine behind an `OcrEngine` protocol | OCR pipeline swapped in without changing the API or any M1/M2 test; API tests run it with a fake engine | In progress |
| NFR-Safety | Clearly support, not replace, clinicians | `formatter.py` + output review | Same as FR10, plus review of answer wording | Not started | Is a separate child-friendly wording needed, and who owns it (C12)? |
| EVAL | Compare against the 5 baselines in PROP Table 5 | `lumi/ml/train_skin.py` (majority-class baseline), `scripts/bootstrap_test_ci.py`, `scripts/check_api_matches_training.py` | Only one baseline done: always-predict-majority-class (accuracy 0.365, macro-F1 0.089). Test numbers carry bootstrap intervals | **In progress, mostly not done.** Missing: single-modality-classifier vs reasoning-layer comparison, default-OCR baseline and CER/WER, VQA-Med baseline, text-only QA baseline, explanation-suppressed comparison | Numeric success criteria (C9) |
| PANEL | Gather and validate data from appropriate sources | `docs/DATA_GOVERNANCE.md` (§5 acquisition log), `docs/data_cards/pad_ufes_20.md`, `docs/templates/`, `tests/test_repo_hygiene.py` | PAD-UFES-20 licence (CC BY 4.0) read on the official Mendeley record; file sizes verified; checksums recorded; VQA-RAD licence (CC0) read on the official OSF API; HAM10000 non-commercial licence recorded; hygiene test keeps data and weights out of Git | In progress: **supervisor approval of datasets is PENDING;** ChestX-ray14 terms **unverified** (official page unreadable by the tools); VQA-RAD not downloaded | What evidence does the panel expect? Supervisor questions in DATA_GOVERNANCE.md §3 and §5.3 |

---

## 8. Contradictions and items needing supervisor confirmation

| ID | Issue | Evidence | Why it matters | Suggested question for supervisor/team |
|---|---|---|---|---|
| **C1** | **Who are the client platforms?** PROP Fig. 3–4 label the web *and* mobile app as IT23256682 ("CBT games, reminders, report view"). In the TAF, IT23256682 builds a *behavioural-screening game feed*, IT23415768 builds an *outbreak 3D-globe web platform*, and IT23207622 builds the robot **and** "the mobile app and backend/database ... report/image upload, and AI chat". No member owns the original "Website: skin lesion detection, X-ray interpretation" from TAF p.2. | TAF p.2 vs p.13–14; PROP Fig. 3, Fig. 4, Table 16 | It decides who your API consumers really are and who signs off the contract | "Which components will actually call LUMI, and who owns the web front-end for skin/X-ray upload?" |
| **C2** | The proposal says "three other components depend on my API contract". Per TAF, the game feed (IT23256682) and the outbreak globe (IT23415768) have no stated need for medical VQA. | PROP §3.6, §4.1 | You might over-build integrations nobody uses | Confirm consumers (same as C1) |
| **C3** | **Outbreak integration is out of scope on paper.** PROP §4.1 says the outbreak component "exchanges aggregated, de-identified signals" with LUMI, but none of your objectives or FRs cover it. | PROP §4.1, Fig. 3 | Silent scope expansion | Proposed default: treat it as **out of scope** unless the supervisor says otherwise |
| **C4** | **OCR ownership overlap.** The robot's tasks include "Integrate the camera module for ... scanning and OCR", and TAF workflow Step 2 shows Tesseract running *before* "Structured JSON sent to AI Backend". PROP says the robot sends a *photo* and LUMI does OCR. | TAF p.8, p.14 vs PROP §4.1 | Two people may build the same thing, or neither may | "Does the robot send a raw image to LUMI, or OCR text?" |
| **C5** | **"Pediatric-specific" vs the data.** HAM10000/ISIC, NIH ChestX-ray14 and VQA-Med are general-population collections, not pediatric datasets (check each dataset's documentation for age statistics). No pediatric data is available until ethics approval. | TAF §9 novelty; PROP §3.2 | The novelty claim needs evidence you may not be able to produce | "What does 'pediatric-oriented' mean for evaluation if no pediatric data is approved?" Possible answer: pediatric-oriented *response design and wording*, not pediatric-trained models |
| **C6** | **Skin domain mismatch.** HAM10000 is *dermatoscopic* images of *pigmented* lesions. The TAF input is "Skin Lesion Photographs (JPEG/PNG)" from phones, and common pediatric skin conditions are mostly not pigmented-lesion classes. | TAF p.3 item 4, p.7; PROP §1.2 | A classifier trained on HAM10000 may be unreliable on phone photos | "Is a HAM10000-only classifier, with this limitation stated, acceptable?" |
| **C7** | **Model commitments differ.** TAF says "Fine-tune ViT **and LLM**", and its architecture names EfficientNet-B4, BioGPT/BioBERT and a cross-modal attention fusion transformer. PROP says "CNN/ViT" and a "reasoning layer", with no committed LLM fine-tuning. | TAF p.7, p.12 vs PROP §4 | It changes compute needs a lot (16 GB Mac); viva examiners may check against the TAF | "Is LLM fine-tuning required, or is a pre-trained model with evidence prompting acceptable?" |
| **C8** | XAI scope: TAF lists Grad-CAM, LIME and SHAP; PROP lists Grad-CAM + evidence spans. | TAF p.7 vs PROP §4 | Scope | Confirm the narrower PROP scope |
| **C9** | **No numeric targets** for latency, API success rate, accuracy or CER/WER. The only comparisons are "lower than baseline" or "high". | PROP Table 6, Table 9 | Without targets you can't say when something is "done" | Agree thresholds with the supervisor before evaluation (I will not invent them) |
| **C10** | **External medical supervisor.** TAF §8 says one is "confirmed", but the External Supervisor row on TAF p.15 is **blank**. The XAI-usefulness and answer-rubric reviews depend on a domain reviewer. | TAF p.9 vs p.15 | Qualitative evaluation may be impossible | "Who is the clinical reviewer, and is that confirmed in writing?" |
| **C11** | **Ethics approval not yet recorded.** It is "To be applied". Any external LLM API that receives health data raises extra privacy questions. | TAF p.10 | Until it is approved, use public and synthetic data only | Current ethics application status? |
| **C12** | **Who writes the child-friendly explanations?** The robot's objective includes "deliver child-friendly AI health explanations", and PROP claims "response phrasing designed for children". | TAF p.14; PROP §6 | Overlap | Agree that LUMI returns a neutral/parent-level answer and the robot adapts tone, or the other way round |
| C13 | Gantt timing vs method: the Gantt starts "Secure REST API development" in **Dec 2026**, but PROP §3.6/§4.1 say a stub API should exist *early* so teammates can integrate. | PROP §9 vs §3.6 | Teammates blocked | Recommend building the stub first (Milestone 1). This only reorders tasks; it doesn't change scope |
| C14 | Smaller wording issues: TAF says "REST / GraphQL" (PROP: REST only); TAF says X-ray "Chest · Bone · Skull" + DICOM (PROP: chest only); "HIPAA/GDPR compliance" should read "principles applied", since a prototype can't claim compliance; the robot is named "KARA" only in PROP. | TAF p.7 vs PROP | Examiner questions | Confirm the narrower PROP wording is the binding version |

---

## 9. Progress log

| Date | Milestone | Requirements touched | Evidence | Notes |
|---|---|---|---|---|
| 2026-10-16 | M0 environment | — | `.venv` with Python 3.12.15; pinned `requirements*.txt` | System Python 3.15 is not used |
| 2026-10-16 | M1 API skeleton | FR1, FR5, FR9, FR10 (stub) | `tests/test_api.py`, `tests/test_validation.py`, `tests/test_service.py` | Mock pipelines only: no predictions, `confidence`/`answer` always null |
| 2026-10-16 | M2 security basics | FR8 (partial), FR11, NFR-Sec (partial) | `tests/test_security.py`; 70 tests passed on assistant's run (student confirmation pending) | API keys from `LUMI_API_KEYS`, fail-closed; in-memory rate limit; logs exclude question text, filenames and metadata values. **Not yet:** HTTPS/TLS (deployment), token issuer decision (C1), role-based access |
| 2026-10-16 | M3a lab-report OCR (synthetic only) | FR4/SO3 (partial), FR7 evidence spans for reports (partial), FR11 | `tests/test_ocr_*.py`; full suite **112 passed, 0 skipped** on assistant's run (student confirmation pending); live server check: 200 response, ~105 ms, no report text in server log | Tesseract 5.5.3 installed via Homebrew, runs locally. Only synthetic, clearly labelled reports were used; no real patient data and no external services. **Not done:** PDFs, phone-photo preprocessing, CER/WER and baseline comparison, real report layouts. C4 (robot vs LUMI OCR) is still open but did not block this step, because OCR is assigned to IT23153318 in TAF §9 |
| 2026-10-16 | Data governance (pre-M3) | PANEL, NFR-Priv, SO1 (preparation only) | `docs/DATA_GOVERNANCE.md`; `docs/data_cards/synthetic_lab_reports.md`; `tests/test_repo_hygiene.py`; full suite **121 passed** on assistant's run | Nothing downloaded; dataset facts are marked "verify at source". Also fixed `/docs` so it shows an **Authorize** button (HTTPBearer); auth behaviour unchanged (all security tests pass; live check: valid key 200, missing/wrong/Basic 401) |
| 2026-10-16 | Dataset inspector (pre-M3) | SO1 (partial), PANEL, NFR-Priv | `lumi/data_inspect/`; `tests/test_data_inspect.py` 40 tests; full suite **161 passed** on assistant's run (student confirmation pending); a deliberate-leak check made 2 privacy tests fail, then the code was restored; run on the 3 synthetic lab reports: 3 ok, 0 corrupt, 0 duplicates | Built from public documentation read on 2026-10-16, because no sample was supplied. HAM10000 licence (CC BY-NC 4.0) verified from the official Dataverse record; other column names are **unverified** and always checked against the real header at run time. No dataset downloaded. Not run on any real dataset yet |
| 2026-10-18 | M3b first image model (skin, PAD-UFES-20) | SO1, FR1-FR3 (skin), FR8, EVAL (partial), PANEL | Full suite **218 passed** on the assistant's run (the 161 earlier tests + 30 ML + 26 skin-API + 1 offline-reproduction; student confirmation pending). Training run `20261018T072750Z`: 12 epochs, best epoch 7 on validation, test (evaluated once) accuracy 0.633, macro-F1 0.543. `scripts/check_api_matches_training.py`: 454 of 454 served test images had an identical predicted class via the API (1 refused as >10 MB). Live demo with the real server and model: health 200, skin 200 with model info, no key 401, OCR 200 (6 rows), chest X-ray placeholder, bad file 415, logs hold no predictions or file names | PyTorch 2.14.1 / timm 1.0.30 / MPS on Apple M5. Dataset PAD-UFES-20 (CC BY 4.0) downloaded; 15 duplicate files found, 12 pairs had conflicting labels (excluded, 24 images). Skin endpoint returns `503 model_unavailable` when no checkpoint is set. **Not clinically validated; no pediatric evidence.** Chest X-ray, VQA, XAI, PDF OCR, CER/WER evaluation still incomplete |

---

## 10. What is genuinely working vs incomplete (2026-10-18)

| Working and verified by tests or measurement | Incomplete or not started |
|---|---|
| API with health check, API-key auth, rate limit, validation, safe logging, standard error format | Chest X-ray analysis (placeholder only) |
| Lab-report OCR on **synthetic** PNG/JPEG reports with honest missing-field flags | Medical VQA (questions accepted, not answered) |
| Skin-lesion classifier (6 classes) trained on PAD-UFES-20, served through the API, matches offline evaluation | Explainability (Grad-CAM etc.) |
| Honest refusal (503) when no model is configured | PDF lab reports; OCR accuracy (CER/WER) and real-report layouts |
| Dataset inspection tool; governance record; data cards; model card; hygiene test | Any pediatric evidence; any clinical validation; ethics approval status unknown |
| 218 automated tests (assistant's run; student confirmation pending) | HTTPS/TLS, deployment, real client integration (C1), numeric targets (C9), supervisor approvals |

Open supervisor questions are listed in §8 above and in `docs/DATA_GOVERNANCE.md` §5.3. Do not describe the skin model as validated, accurate enough for patients, or reliable for children.
