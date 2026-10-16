# LUMI — Multimodal AI/ML Backend (J26-IT-445, IT23153318)

Research prototype for **decision support only**. It does not diagnose and does not replace licensed clinicians.

Current state: API skeleton with validation, API-key auth, rate limiting and privacy-safe logging.
Skin and chest X-ray pipelines are **mocks that make no predictions**. Lab reports (PNG/JPEG) go through local Tesseract OCR and field parsing; PDFs are not analysed yet. Scope and open questions: [docs/SCOPE_REVIEW.md](docs/SCOPE_REVIEW.md).

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

Every response, including errors, uses the same JSON envelope and carries `request_id` and `clinical_boundary_notice`.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `LUMI_API_KEYS` | *(empty → all /api requests rejected)* | `client_id:key` pairs, comma-separated, keys of 16+ characters |
| `LUMI_RATE_LIMIT_PER_MINUTE` | `60` | Per-client request limit |
