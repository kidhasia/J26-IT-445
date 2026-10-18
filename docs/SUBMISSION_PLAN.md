# LUMI submission plan (report, slides, demonstration)

## 0. What I could and could not verify
- **Found in the project files:** the proposal (`J26-IT-445 - IT23153318.pdf`, 35 pages) and the Topic Assessment Form. Their work breakdown lists two documentation deliverables: **1.6.2 "Compile final report content"** and **1.6.3 "Prepare final presentation and viva materials"**. The Gantt chart schedules "Final report and viva preparation" and "Final evaluation and baseline comparison" up to **April 2027**.
- **Not found:** a university thesis template, a marking rubric, a required page or word limit, a slide template, or a stated deadline. **I have not invented any of these.** The report outline below follows the *proposal's own* chapter structure and is a starting skeleton, not the official format.
- **The "3 days" deadline** was stated by you; nothing in the repository confirms which assessment it is for (progress presentation, interim report, final demonstration, viva). Please tell me which, and send the template or rubric if you have one.

## 1. Report skeleton (reuse the proposal's headings; evidence already written is named)
| Chapter | Content to write | Source already in the repository |
|---|---|---|
| Abstract | Problem, what was built, what was measured, what was not | `docs/EVIDENCE_PACKAGE.md` §0 |
| 1 Introduction | Background, literature, gap (reuse proposal §1) | Proposal §1.1 to 1.3 |
| 2 Objectives | Main and specific objectives, with status per objective | `docs/SCOPE_REVIEW.md` §7 (traceability table) |
| 3 Methodology | Pipeline design, data, baselines, metrics, validation | Proposal §3; model card §1 to 2; `docs/DATA_GOVERNANCE.md` |
| 4 Implementation | Architecture, API, skin model, Grad-CAM, OCR, Q&A, interface, security | `README.md`, `lumi/`, `docs/EVIDENCE_PACKAGE.md` §2 to 6 |
| 5 Results and evaluation | Skin metrics with intervals, Grad-CAM checks, OCR CER/WER, Q&A check, tests | Model card §3, §9; `docs/OCR_EVALUATION.md`; `docs/evaluations/qa_results.json` |
| 6 Discussion | What the numbers do and do not show; limitations (pediatric, melanoma, synthetic OCR, in-sample Q&A) | Evidence package §2 to 5, §8 |
| 7 Conclusion and future work | Chest X-ray plan, VQA, clinician review, real documents, integration | `docs/CHEST_XRAY_PLAN.md`, evidence package §7 |
| References | Cite only what you have actually read; the dataset citations are in governance §5.2 | Proposal §10 |
| Appendices | Model card, data cards, test/command list, completion assessment | `docs/` |

## 2. Slide outline (about 12 slides, 10 to 12 minutes)
1. Title, component and what LUMI is (a research prototype, decision support only).
2. Problem and gap (one slide from the proposal).
3. Architecture: one request flow (image or report in, structured answer and warnings out).
4. What is built versus not built (the table in the evidence package §0). Honesty here earns trust.
5. Skin model: data, patient-level split, measured results and the baseline.
6. Skin model limits: melanoma 11 images, SCC weak, children 6 test photos, one in three wrong.
7. Grad-CAM: the picture, the sanity checks, and "not a diagnosis".
8. Lab-report reading: demo result, CER 1.26% / WER 11.67%, "three synthetic reports only".
9. Evidence-grounded questions: examples, the refusal sentence, 38 of 38 in-sample and 12 of 17 on new wording.
10. Security and testing: 435 tests, 94 browser checks, privacy-safe logs.
11. What remains and why (chest X-ray gate, approvals, clinical review) and the plan.
12. Questions for the supervisor (the open decisions in `docs/SCOPE_REVIEW.md` §8).

## 3. Live demonstration (about 8 minutes)
Before: run `./scripts/demo_preflight.sh` (it reads only; it must print `READY`).
1. Double-click `scripts/start_demo.command`. Wait for the page. (30 s)
2. **Skin Analysis:** drop one photo from `data/raw/PAD-UFES-20/images/imgs_part_1/`, keep the attention map on. Say aloud: "relative scores, not a diagnosis; wrong about 1 in 3". (2 min)
3. **Lab Reports:** `syn_0002_missing_value.png`. Point to **Not found**: "it never guesses a missing value". (1.5 min)
4. **Ask a question:** pick the lab result and ask *"Which lab values were not found?"*, then *"What was the reported haemoglobin value?"*; then the skin result with *"What limitations apply to this result?"*; then show the refusals: *"Is this cancer?"* and *"Is my haemoglobin normal?"*. Point to the evidence-not-verified warning. (2.5 min)
5. **Chest X-ray page:** "in development, nothing is analysed". **About** page: the limits. (1 min)
6. Show `docs/EVIDENCE_PACKAGE.md` §0 on screen as the honest status. (1 min)

## 4. Backup plan if something fails
| Failure | What to do |
|---|---|
| Page says "Could not reach the server" | In Terminal run `./scripts/start_demo.command` again; wait for "Application startup complete". Port busy: it stops the old copy itself |
| "Model not set up" (red) | `ls models/skin_pad_ufes20/` must show `20261018T072750Z`. If missing, skip the skin demo and use the screenshots below; retraining takes about 7 minutes (`docs/MODEL_CARD_skin_pad_ufes20.md` §8) |
| Lab reading "not available" | `brew install tesseract`, or show the saved results `docs/evaluations/ocr_synthetic_results.json` |
| Browser problems | Use the API: the `curl` commands in `README.md` ("Asking questions about a result") and the developer page at http://localhost:8000/docs |
| Whole laptop or server fails | Show **screenshots** (run beforehand: `scripts/ui_smoke_test.py ...` saves them in `data/processed/ui_smoke/`; copy 4 or 5 into the slides) and the saved outputs: `docs/evaluations/qa_results.json`, the model card tables, and `pytest` output captured earlier |
| Key rejected (401) | Click **API key**, paste `local-dev-key-not-for-production` (printed by `run_dev.sh`) |
Tip: record a 3-minute screen recording of a good run beforehand as the last-resort backup.

## 5. Tasks for you (I cannot do these)
1. Tell me which assessment is in 3 days, and send the template or rubric. 2. Send your supervisor the questions in `docs/SCOPE_REVIEW.md` §8 (especially C1, C5, C7, C10, C11, C15). 3. Log in to GitHub and run `git push -u origin main develop` once (`gh auth login` first). 4. Write the report chapters in your own words from the table in §1. I can help turn the existing documents into draft text, but **the report is your work and must be checked by you**. 5. Rehearse the demo twice.
