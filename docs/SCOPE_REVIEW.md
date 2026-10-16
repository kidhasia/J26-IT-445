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
Module paths are *proposed* and do not exist yet.

| ID | Requirement | Implementation module | Test / evidence | Status | Open question |
|---|---|---|---|---|---|
| SO1 | Collect and preprocess data; fixed, recorded train/val/test splits | `lumi/data/`, `scripts/make_splits.py`, `data/splits/*.csv` | Split manifest files committed; checksum/count report; check that no patient overlaps across splits | Not started | Which datasets have actually been downloaded and accepted under licence? Is any local data covered by ethics approval? |
| FR1 | Accept skin and chest X-ray images through the API | `lumi/api/routes.py`, `lumi/api/validation.py` | pytest: valid PNG/JPEG accepted; wrong type and oversize rejected with a validation error | Not started | Accepted formats (DICOM?) and maximum file size? |
| FR2 | Preprocess images (resize, normalise, colour) | `lumi/pipelines/skin/preprocess.py`, `lumi/pipelines/cxr/preprocess.py` | Unit tests on output shape and value range; visual check of a sample (App. C) | Not started | — |
| FR3 / SO2 | Image analysis returns class + confidence | `lumi/pipelines/skin/`, `lumi/pipelines/cxr/` | Accuracy, balanced accuracy, per-class F1, ROC-AUC on the fixed test split vs the single-modality baseline | Not started | Which label set? Are pediatric-relevant classes required (see C5, C6)? |
| FR4 / SO3 | OCR on lab reports → text + parsed fields | `lumi/pipelines/ocr/` | CER/WER vs ground-truth transcriptions on synthetic reports, compared with default Tesseract; manual review of a sample | Not started | Which report layouts and fields? Does LUMI or the robot do OCR (C4)? |
| FR5 | Accept natural-language questions | `lumi/api/schemas.py` | pytest: empty, overlong and missing-question cases | Not started | Languages: English only, or Sinhala/Tamil too? Neither document says |
| FR6 / SO4 | Combine evidence + question → context-aware answer | `lumi/reasoning/` | VQA-Med EM/F1 where compatible; rubric scores per question type; comparison with the text-only baseline | Not started | Fine-tune an LLM (TAF) or use a pre-trained model with evidence prompting (C7)? Local model or external API (privacy, C11)? |
| FR7 / SO5 | Explainable output (saliency map / evidence span) | `lumi/xai/` | Grad-CAM sanity checks; explanation-usefulness rubric; with-vs-without-explanation comparison | Not started | Who are the reviewers (C10)? Are Grad-CAM + evidence spans enough, or are LIME/SHAP required (C8)? |
| FR8 / SO6 | Secure REST API used by the clients | `lumi/api/`, `lumi/api/auth.py` | pytest: no token → 401; bad token → 401; rate limit → 429; HTTPS in deployment config | Not started | Who issues tokens: LUMI or the team backend? Which clients really call it (C1)? |
| FR9 | Distinct, structured success / validation-error / failure responses | `lumi/api/schemas.py` (envelope) | Contract tests: every response validates against the envelope schema | Not started (schema specified in App. A) | Need an agreed list of error codes with client owners |
| FR10 | Clinical boundary notice on every applicable response | `lumi/api/formatter.py` | Automated test: notice present in every success response; output review | Not started | Exact wording needs supervisor approval. Include it on error responses too? |
| FR11 | Logs good enough for debugging/evaluation, with no unnecessary PII | `lumi/logging_config.py` | Test that logs contain no file bytes, names or raw question text unless approved; log inspection | Not started | Where do logs go (local file vs team DB)? Retention period? |
| NFR-Perf | Latency "fast enough for bedside interaction" | `scripts/bench_latency.py` | Per-pipeline and end-to-end latency recorded on every run | Not started | **No numeric target** (C9) |
| NFR-Rel | Consistent processing; invalid requests rejected safely | `tests/test_reliability.py` | Success/error rate over repeated runs | Not started | **No numeric target** (C9) |
| NFR-Sec | Data protected in transit; controlled access | `lumi/api/auth.py`, deployment config | Unauthenticated access verified as rejected | Not started | Where is it deployed, and who manages TLS? |
| NFR-Priv | Keep only necessary data; de-identified data for research | Data-handling doc | Review against the project ethics position | Not started | Blocked on the ethics approval status |
| NFR-Scale | Several clients share one service | `scripts/load_test.py` | Concurrent-request test within prototype scope | Not started | Expected number of concurrent users? |
| NFR-Maint | Vision, OCR, VQA, XAI and API modules independently replaceable | Package structure + interface docs | Each pipeline has its own unit tests and a documented interface | Not started | — |
| NFR-Safety | Clearly support, not replace, clinicians | `formatter.py` + output review | Same as FR10, plus review of answer wording | Not started | Is a separate child-friendly wording needed, and who owns it (C12)? |
| EVAL | Compare against the 5 baselines in PROP Table 5 | `lumi/eval/` | Results tables per baseline, with splits fixed beforehand | Not started | Numeric success criteria (C9) |
| PANEL | Gather and validate data from appropriate sources | `docs/DATA_SOURCES.md` | Licence, provenance and validation record for each dataset | Not started | What evidence does the panel expect? |

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
