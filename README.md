# LUMI — Multimodal AI/ML Backend (J26-IT-445, IT23153318)

Research prototype for **decision support only**. It does not diagnose and does not replace licensed clinicians.

Current state (see the status table below for exactly what is real):
API with validation, API-key auth, rate limiting and privacy-safe logging; lab-report OCR on PNG/JPEG images (local Tesseract);
a skin-lesion classifier fine-tuned on the public PAD-UFES-20 dataset (6 classes, adults almost exclusively).
Skin results can optionally include a Grad-CAM attention map (a coarse picture of what influenced the model; not a diagnosis). Chest X-ray analysis and image-based medical VQA are **not implemented**; a small rule-based question-answering endpoint exists (see below). Scope and open questions: [docs/SCOPE_REVIEW.md](docs/SCOPE_REVIEW.md).


## What works today

| Part | Status |
|---|---|
| `GET /health`, auth, rate limit, validation, safe logging | Working, tested |
| Lab-report OCR (`input_type=lab_report`, PNG/JPEG) | Working on **synthetic** reports. Measured on 3 clean synthetic reports only (character error 1.3%, word error 11.7%, almost all of it moved spaces; see `docs/OCR_EVALUATION.md`); PDFs and real reports not done |
| Skin-lesion classifier (`input_type=skin_image`) | Working **when a trained checkpoint is configured**; otherwise the endpoint answers `503 model_unavailable` and never invents a prediction. Research prototype, not clinically validated (see `models/` run metrics and `docs/DATA_GOVERNANCE.md` §5) |
| Chest X-ray (`input_type=chest_xray`) | **Placeholder only**: returns `status: not_implemented`, no prediction |
| Attention map for skin photos (Grad-CAM, send `explain=true`) | Working and tested. Coarse (8 by 8 cells). Passed a deletion test and a randomisation test on the held-out images (model card §9). It describes the model, **not** the lesion, and has not been reviewed by clinicians |
| Evidence-grounded questions (`POST /api/v1/ask`) | Working, tested, small. Rule-based; answers only from an analysis result you supply; see [Asking questions](#asking-questions-about-a-result). It is **not** image question answering (VQA) and not a medical chatbot |

**Results, limits and how to demonstrate it:** `docs/MODEL_CARD_skin_pad_ufes20.md` (real test results and limitations),
`docs/DEMO_GUIDE.md` (step-by-step demo for your supervisor), `docs/CHEST_XRAY_PLAN.md` (chest X-ray research, approval gate and pilot plan; nothing downloaded), `docs/OCR_EVALUATION.md` (lab-report OCR accuracy on synthetic reports, with how to reproduce it), `docs/COMPLETION_ASSESSMENT.md` (how complete the project really is, and how that was calculated), `docs/SCOPE_REVIEW.md` (traceability and progress),
`docs/DATA_GOVERNANCE.md` (datasets, licences, what is verified and what is pending).
The skin model is a research prototype: not clinically validated, and not shown to be reliable for children.

## Start the demo page (easiest way)

Double-click `scripts/start_demo.command` in Finder, or run `./scripts/run_dev.sh` in a terminal, then open **http://localhost:8000/**.
The interface has five pages (Overview, Skin Analysis, Lab Reports, Chest X-ray, About LUMI). It shows what is really working, lets you drop in a practice file, and explains the result in plain language. The Chest X-ray page is deliberately an "In development" page with no upload, because no chest X-ray model exists yet.
The developer page is at http://localhost:8000/docs. The demo page is off unless `LUMI_DEMO_UI=1` (the start script sets it),
so a real deployment serves only the API.

The interface is plain HTML, CSS and JavaScript in `lumi/demo_ui/` (no framework, no external files, no inline code, strict Content-Security-Policy).
To test it in a real browser (needs Google Chrome): `.venv/bin/python scripts/ui_smoke_test.py --skin-image PATH_TO_A_PNG --lab-image data/synthetic/lab_reports/syn_0001_complete.png`.

## Train the skin-lesion model (needs the PAD-UFES-20 data under `data/raw/`)

```bash
.venv/bin/python -m lumi.ml.train_skin \
    --metadata data/raw/PAD-UFES-20/metadata.csv \
    --images data/raw/PAD-UFES-20/images \
    --out-dir models/skin_pad_ufes20
```

About 5 minutes on an Apple-silicon Mac (GPU via MPS). Each run is saved in `models/skin_pad_ufes20/<run id>/` with
`checkpoint.pt`, `metrics.json`, `config.json` (seed, versions, split sizes, git commit) and `training_log.csv`.
`models/` and `data/` are ignored by Git. Dataset download and licence record: `docs/DATA_GOVERNANCE.md` §5.

## Use the trained model in the API

`./scripts/run_dev.sh` uses the newest checkpoint automatically. To choose one yourself, point `LUMI_SKIN_MODEL_PATH` at it (only load checkpoints you trained yourself or trust):

```bash
export LUMI_SKIN_MODEL_PATH="$PWD/models/skin_pad_ufes20/<run id>/checkpoint.pt"
./scripts/run_dev.sh
```

Check that the API reproduces the offline test evaluation, measure the uncertainty of the test numbers, and sanity-check the attention maps (all print aggregates only):

```bash
.venv/bin/python scripts/check_api_matches_training.py models/skin_pad_ufes20/<run id> \
    data/raw/PAD-UFES-20/metadata.csv data/raw/PAD-UFES-20/images
.venv/bin/python scripts/bootstrap_test_ci.py models/skin_pad_ufes20/<run id> \
    data/raw/PAD-UFES-20/metadata.csv data/raw/PAD-UFES-20/images
.venv/bin/python scripts/check_gradcam_faithfulness.py models/skin_pad_ufes20/<run id> \
    data/raw/PAD-UFES-20/metadata.csv data/raw/PAD-UFES-20/images
```

## Setup (once)

```bash
cd "/Users/kidhasia/Desktop/Research Stuff"
/opt/homebrew/bin/python3.12 -m venv .venv          # skip if .venv already exists
.venv/bin/pip install -r requirements-dev.txt
```

## OCR prerequisite

```bash
brew install tesseract
.venv/bin/python scripts/make_synthetic_lab_reports.py   # sample synthetic reports in data/synthetic/lab_reports/
```

## Measure the lab-report OCR accuracy (synthetic reports; needs Tesseract)

```bash
.venv/bin/python scripts/make_synthetic_lab_reports.py     # only if data/synthetic/lab_reports is missing
.venv/bin/python -m lumi.eval.ocr_eval                      # verifies the references, scores LUMI vs plain Tesseract, writes docs/evaluations/ocr_synthetic_results.json
```
Details, results and limitations: `docs/OCR_EVALUATION.md`.

## Run tests

```bash
.venv/bin/python -m pytest -v
```

## Inspect a dataset (read-only)

Counts, label distribution, missing values, corrupt and duplicate files and image sizes. It never changes the data and never prints file names, ids or row values.

```bash
.venv/bin/python -m lumi.data_inspect --name myset --images "PATH/TO/IMAGES" --metadata "PATH/TO/METADATA.csv" \
    --label-column LABEL_COLUMN --id-column ID_COLUMN --group-column PATIENT_OR_LESION_COLUMN
# or use a preset for a known dataset: --preset ham10000   (or nih_cxr14)
```

Results go to `data/processed/inspection/<name>_summary.json` and `<name>_report.md` (ignored by Git).
Column names are always checked against the real file header; mismatches are reported with suggestions.
Add `--list-problem-files` to also save the paths of corrupt/duplicate files locally.

## Run the server

```bash
./scripts/run_dev.sh
```

Then open http://localhost:8000/docs. Click **Authorize** and paste the key the script prints.

Example request from a second terminal:

```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Authorization: Bearer local-dev-key-not-for-production" \
  -F input_type=skin_image \
  -F "file=@/path/to/image.png;type=image/png" \
  -F "question=What does this show?"
```

## Asking questions about a result

`POST /api/v1/ask` answers simple factual questions about **one analysis result you already have** (the JSON that
`/api/v1/analyze` returned for a skin photo or a lab report). It uses fixed rules only: no language model, no internet, nothing stored.

```bash
# 1. analyse a lab report and keep the answer
curl -s -X POST http://localhost:8000/api/v1/analyze -H "Authorization: Bearer local-dev-key-not-for-production" \
  -F input_type=lab_report -F "file=@report.png;type=image/png" > analysis.json

# 2. ask a question about it
python3 -c 'import json; print(json.dumps({"question": "Which lab values were not found?", "evidence": json.load(open("analysis.json"))}))' |
  curl -s -X POST http://localhost:8000/api/v1/ask -H "Authorization: Bearer local-dev-key-not-for-production" \
  -H "Content-Type: application/json" --data @-
```

The reply uses the usual envelope; the text is in `answer`. Questions it can answer: the predicted skin class, the top or per-class
score, the attention map, the model, limitations and warnings; for lab reports, a named test's value, unit or range (for example
"What was the reported haemoglobin value?"), which values, units or ranges were not found, which rows need review, how many rows
were found, the text-reading confidence, and limitations.

**Limits (read these):**
- Anything else gets exactly: `I cannot answer this from the available evidence.` This includes diagnosis, "is it cancer?", "is it normal?", treatment or advice, tests that are not on the report, and questions about the other kind of result.
- LUMI does **not** check that the evidence is genuine or unchanged (the reply carries an `EVIDENCE_NOT_VERIFIED` warning). Anyone who edits the evidence changes the answer.
- English keyword matching only. Odd phrasing may be refused even when the answer is in the evidence. It does not understand images, only the structured result.
- Only skin-photo and lab-report results are accepted (not the chest X-ray placeholder). Questions are at most 500 characters and the body at most 300,000 bytes. Same API key and rate limit as `/analyze`.
- The question, the evidence and the answer are never written to the log. Not evaluated on real users or real reports; not clinically validated.

## API summary

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` | none | Liveness check |
| `POST /api/v1/ask` | `Authorization: Bearer <key>` | JSON: `question` (text, up to 500 characters) and `evidence` (the JSON that `/analyze` returned for a skin photo or lab report). Answers only from the evidence |
| `POST /api/v1/analyze` | `Authorization: Bearer <key>` | Multipart: `input_type` (`skin_image` \| `chest_xray` \| `lab_report`), `file`, optional `question`, optional `metadata` (JSON with only `client_platform`, `client_version`, `locale`), optional `explain` (`true` adds a Grad-CAM attention map to skin results; off by default) |

| Status | `error.code` | Meaning |
|---|---|---|
| 400 | `empty_file`, `unreadable_file` | File empty, corrupt, truncated, encrypted PDF |
| 401 | `unauthorized` | Missing or wrong API key |
| 413 | `file_too_large` | Over 10 MB, over 50M pixels, or over 20 PDF pages |
| 415 | `unsupported_media_type` | Type not allowed for this input_type, or contents don't match the declared type |
| 422 | `missing_field`, `invalid_input_type`, `invalid_field`, `invalid_metadata` | Bad form fields |
| 429 | `rate_limited` | Over 60 requests/minute per client (`Retry-After` header given) |
| 500 | `internal_error` | Unexpected failure (no internal details returned) |
| 503 | `ocr_unavailable` | Tesseract missing or timed out |
| 503 | `model_unavailable` | Skin model not configured or could not be loaded |

Every response, including errors, uses the same JSON envelope and carries `request_id` and `clinical_boundary_notice`.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `LUMI_API_KEYS` | *(empty → all /api requests rejected)* | `client_id:key` pairs, comma-separated, keys of 16+ characters |
| `LUMI_RATE_LIMIT_PER_MINUTE` | `60` | Per-client request limit |
| `LUMI_DEMO_UI` | *(off)* | `1` serves the demo page at `/` and `/demo` (local use only) |
| `LUMI_DEMO_UI_KEY` | *(none)* | Key pre-filled in the demo page; only ever a throw-away local development key |
| `LUMI_SKIN_MODEL_PATH` | *(unset → skin endpoint answers 503)* | Path to a trained `checkpoint.pt` |
