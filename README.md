# LUMI — Multimodal AI/ML Backend (J26-IT-445, IT23153318)

Research prototype for **decision support only**. It does not diagnose and does not replace licensed clinicians.

Current state (see the status table below for exactly what is real):
API with validation, API-key auth, rate limiting and privacy-safe logging; lab-report OCR on PNG/JPEG images (local Tesseract);
a skin-lesion classifier fine-tuned on the public PAD-UFES-20 dataset (6 classes, adults almost exclusively).
Chest X-ray, medical VQA and explainability are **not implemented**. Scope and open questions: [docs/SCOPE_REVIEW.md](docs/SCOPE_REVIEW.md).


## What works today

| Part | Status |
|---|---|
| `GET /health`, auth, rate limit, validation, safe logging | Working, tested |
| Lab-report OCR (`input_type=lab_report`, PNG/JPEG) | Working on **synthetic** reports; PDFs and real reports not done; accuracy not yet measured (CER/WER pending) |
| Skin-lesion classifier (`input_type=skin_image`) | Working **when a trained checkpoint is configured**; otherwise the endpoint answers `503 model_unavailable` and never invents a prediction. Research prototype, not clinically validated (see `models/` run metrics and `docs/DATA_GOVERNANCE.md` §5) |
| Chest X-ray (`input_type=chest_xray`) | **Placeholder only**: returns `status: not_implemented`, no prediction |
| Medical VQA, explainability (Grad-CAM) | Not started. Questions are accepted but not answered |

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

Point `LUMI_SKIN_MODEL_PATH` at a checkpoint (only load checkpoints you trained yourself or trust):

```bash
export LUMI_SKIN_MODEL_PATH="$PWD/models/skin_pad_ufes20/<run id>/checkpoint.pt"
./scripts/run_dev.sh
```

Check that the API reproduces the offline test evaluation (prints aggregates only):

```bash
.venv/bin/python scripts/check_api_matches_training.py models/skin_pad_ufes20/<run id> \
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

## API summary

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` | none | Liveness check |
| `POST /api/v1/analyze` | `Authorization: Bearer <key>` | Multipart: `input_type` (`skin_image` \| `chest_xray` \| `lab_report`), `file`, optional `question`, optional `metadata` (JSON with only `client_platform`, `client_version`, `locale`) |

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
| `LUMI_SKIN_MODEL_PATH` | *(unset → skin endpoint answers 503)* | Path to a trained `checkpoint.pt` |
