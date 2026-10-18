# Completion assessment (2026-10-18)

Made from the repository as it is today (3,887 lines of Python in `lumi/`, 17 test files with 431 passing tests, a 1,236-line web interface, 10 documents), the proposal (`J26-IT-445 - IT23153318.pdf`), the Topic Assessment Form, and `docs/SCOPE_REVIEW.md`.

**These percentages are my judgement, not measurements.** Each component's score and weight is a choice made explicit below so you can disagree with it, and I would treat each result as **plus or minus about 5 points**. They are meant to be sobering, not flattering.

## The two numbers

| | |
|---|---|
| **A. Functional prototype: about 46%** | How much of the required *software* is genuinely implemented **and working** end to end |
| **B. Overall research project: about 35%** | Everything a final-year submission needs: software, data, experiments, validation, approvals, integration, thesis and presentation |

**Why these differ from my earlier "about 41%".** That figure was a rough blend. These are calculated from stated weights, and the two chest X-ray and question-answering gaps weigh heavily because the project's title promises that LUMI "reads, understands and explains" images and reports, and neither of those two parts exists yet.

## What counts, and what does not

- **Counts toward A:** code that exists, runs in the real application, is covered by tests, and does what the requirement says for the scope the proposal describes.
- **Does not count toward A:** a polished look, a placeholder that returns "not implemented", a plan, a document, or a high test count. Tests show the *code* behaves as written; they say nothing about whether the *science* is right.
- **Kept out of A on purpose:** model accuracy, scientific validation and clinical validation. They count toward B only, and only when they have actually been done.
- Scale for each component: 0 = nothing; about 5 = placeholder or plan only; 50 = works for part of the scope; 65 to 85 = works with named gaps; 90+ = complete for the proposal's scope.

## Implementation, scientific validation and clinical validation are three different things

| Part | Implemented and working | Scientifically validated (measured on held-out data, method documented) | Clinically validated (experts, real patients, real documents) |
|---|---|---|---|
| Skin classifier | **Yes** (first model, served through the API) | **Partly.** 455 held-out photos, accuracy 0.63, macro-F1 0.54, confidence intervals, one baseline. Adult-dominated data, 11 melanoma cases, one run, no external test set | **No** |
| Attention map (Grad-CAM) | **Yes** (skin only) | **Partly.** Deletion and randomisation sanity checks pass. Nothing about usefulness | **No** (no clinician has seen it) |
| Lab-report OCR | **Yes** (images, synthetic) | **Barely.** 3 clean synthetic reports, CER 1.26%, WER 11.67%, versus plain Tesseract | **No** (no real or photographed report) |
| Chest X-ray | **No** (placeholder) | No | No |
| Question answering | **Smallest version only** (rule-based, from a supplied result) | **No** (no accuracy measured) | No |
| Pediatric reliability | n/a | **No evidence at all** (39 under-18 skin images, all benign nevus) | No |

## A. Functional prototype: calculation

| Component | Weight | Done | Contribution | Basis |
|---|---|---|---|---|
| REST API and security | 15 | 85% | 12.75 | Keys, rate limit, validation, errors, safe logging, tests. Missing: HTTPS, deployment, role-based access, who issues tokens (C1), load test |
| Skin pipeline | 12 | 90% | 10.80 | Preprocess, trained model, API, tests. Accuracy is a B matter |
| Lab-report OCR | 10 | 65% | 6.50 | Images only. No PDF, no phone-photo correction, one synthetic layout |
| **Chest X-ray pipeline** | 15 | **5%** | 0.75 | Placeholder endpoint and an honest "In development" page. No model, no data |
| **Question answering / reasoning** | 20 | **15%** | 3.00 | `/api/v1/ask` answers fixed factual questions from a supplied skin or lab result and refuses the rest. No model, no image reasoning, no evaluation, not in the interface |
| Explainability | 10 | 50% | 5.00 | Skin maps and OCR evidence lines. None for chest or questions |
| Safety and limitation output | 3 | 90% | 2.70 | On every response; supervisor-approved wording still pending |
| Demonstration interface | 5 | 80% | 4.00 | Five pages, honest status, tested in Chrome. Not the team's mobile or web apps |
| Integration with the team's robot, mobile and web components | 10 | 5% | 0.50 | An API contract exists; nothing is connected; who calls LUMI is still unclear (C1) |
| **Total** | **100** | | **46.00** | |

Cross-checks (both are less trustworthy than the weighted result):
- **Equal weights** for all nine components: 53.9%. Too generous, because it counts the 5% chest X-ray piece the same as the 85% API.
- **Counting the proposal's 11 functional requirements equally** (FR1 to FR11, each scored 0 to 100): about 68%. **Inflated**: most FRs describe infrastructure (accept a file, return a structured error, log safely) that is largely built, while the two hardest capabilities carry only one or two lines each.

### Requirements by state
- **Completed (for the prototype's scope):** FR9 structured responses, FR11 safe logging, FR10 boundary notice (wording pending), FR8 secure endpoints (no TLS), skin intake, preprocessing and classification, the demo interface.
- **Partly completed:** FR1 (chest uploads are accepted but not analysed), FR2 and FR3 (skin only), FR4 OCR, FR5 (questions are accepted but not answered), FR7 explainability, six of the seven non-functional requirements (see `docs/SCOPE_REVIEW.md` §7).
- **Unfinished:** FR6 (only the smallest rule-based version exists; nothing combines the image itself with a question), chest X-ray analysis, any model-based or image-based question answering, PDF reports, HTTPS and deployment, load and latency measurement, integration with other components.

## B. Overall research project: calculation

| Category | Weight | Done | Contribution | Basis |
|---|---|---|---|---|
| Research foundation | 10 | 85% | 8.50 | Proposal, literature, gap, method, TAF accepted, scope review with 16 open questions |
| Data acquisition and governance | 10 | 35% | 3.50 | PAD-UFES-20 obtained and inspected, synthetic reports; chest X-ray, question-answering and any clinical data not obtained; no supervisor or ethics approvals |
| Software prototype | 25 | 46% | 11.50 | = A |
| Experiments and evaluation | 15 | 30% | 4.50 | Skin results with intervals and one baseline; OCR vs plain Tesseract on synthetic text; attention-map sanity checks. Missing: chest, question answering, four of the proposal's five baseline comparisons, an integrated-versus-fragmented comparison |
| Scientific and clinical validation | 10 | 2% | 0.20 | No clinician review, no pediatric data, no real reports |
| Approvals, ethics and team integration | 10 | 10% | 1.00 | Questions drafted; none answered; nothing integrated |
| Documentation and reproducibility | 5 | 75% | 3.75 | Model card, data cards, governance record, evaluation reports, demo guide, 431 tests, reproducible commands |
| Final thesis | 10 | 5% | 0.50 | Evidence is accumulating in the documents; no thesis chapters written |
| Presentation and viva | 5 | 30% | 1.50 | A working demo and a demo guide; no slides or viva preparation |
| **Total** | **100** | | **34.95** | |

**Cross-check on the proposal's own work breakdown.** The proposal lists 25 leaf tasks. Counting each task equally gives 59%, which is inflated because it treats "submit the proposal" like "build question answering". Weighting each task by my estimate of its hours gives **44%** (293 of 663 hours). That is higher than 34% because the work breakdown leaves out approvals, clinical and pediatric validation and team integration, which the 34% includes.

**Against the calendar.** The proposal's Gantt chart runs August 2026 to April 2027, and 29% of that time has passed. At 35% we are slightly ahead of the calendar overall, and ahead on the API, skin model and OCR (which the Gantt schedules for later). But the chest X-ray work (planned from November) and question answering (December to February) have not started, and they are the largest remaining pieces.

## What remains to reach a demonstrable final-year submission

Estimates, with large uncertainty (roughly plus or minus 40%):

| Work | Hours |
|---|---|
| Work-breakdown tasks not yet done (chest X-ray pilot, question answering, evaluation, integration, thesis, slides) | about 370 |
| Not in the work breakdown: approvals and ethics paperwork, team integration, reviewer sessions, robustness on realistic inputs | about 85 to 170 |
| **Total** | **about 455 to 540 hours** |

At 20 hours a week that is 23 to 27 weeks; at 30 hours a week, 15 to 18 weeks. About 28 weeks remain to the end of April 2027 (23 weeks to the end of March). **So it is feasible, but tight at 20 hours a week, and only if approvals arrive within a few weeks and the scope is kept disciplined.**

**A realistic minimum for a defensible submission:** the secure API and interface; skin classification with attention maps and an honest evaluation; lab-report reading with its evaluation; a chest X-ray pilot model with a pilot-level evaluation; a minimal but real question-answering feature with its own evaluation; every limitation stated, especially no clinical validation and no pediatric evidence; supervisor sign-off on datasets; and a thesis built from the documents that already exist.

## Next three priorities

1. **Get supervisor decisions** (`docs/CHEST_XRAY_PLAN.md` §7 and `docs/SCOPE_REVIEW.md` §8): approval to use a chest X-ray dataset, whether "unrestricted with attribution" is enough, whether an adult-weighted dataset is acceptable, who calls LUMI (C1), who does OCR (C4), and numeric targets (C9). Nothing else on the critical path can finish without these.
2. **Decide what "question answering" will mean beyond the smallest version now built (`/api/v1/ask`).** It is the largest missing piece (20% of A). The decision (C7: fine-tune a model, or use a small pre-trained model with the extracted evidence) changes the compute, data and risk.
3. **After approval, run the chest X-ray pilot** (metadata first, then one archive), and in parallel **agree the API contract with your teammates** so integration is not left to the last weeks.

## Decisions needed from you
- Which meaning of "question answering" to build (priority 2). My recommendation is the evidence-grounded version: answer questions about the lab-report fields and the skin result with a small local model, rather than fine-tuning a large vision-language model, because that fits your Mac and the proposal's privacy rules.
- Whether to take the chest X-ray questions to your supervisor first (recommended) or wait.
