# LUMI demonstration guide (for you and your supervisor)

Everything below runs on your MacBook. Nothing is sent over the internet. Time needed: about 10 minutes.

## Before you start (once)
Open a terminal in VS Code and run:
```bash
cd "/Users/kidhasia/Desktop/Research Stuff"
.venv/bin/python -m pytest -q          # expect: 218 passed
ls models/skin_pad_ufes20/              # you should see a folder named 20261018T072750Z
```
If `models/` is missing, the trained model is not on this machine; retrain with the command in `docs/MODEL_CARD_skin_pad_ufes20.md` §8 (about 7 minutes).

## Step 1: start the server with the model
```bash
export LUMI_SKIN_MODEL_PATH="$PWD/models/skin_pad_ufes20/20261018T072750Z/checkpoint.pt"
./scripts/run_dev.sh
```
Wait for `Application startup complete.` Leave this terminal alone. Open a **second** terminal tab for anything else.

## Step 2: open the interactive page
Browser: **http://localhost:8000/docs**
Click **Authorize**, paste `local-dev-key-not-for-production`, click Authorize, then Close.

## Step 3: show each working feature
Open `POST /api/v1/analyze`, click **Try it out**, choose an `input_type`, pick a file, click **Execute**.

| What to show | input_type | File to upload | What you should see |
|---|---|---|---|
| Lab-report reading | `lab_report` | `data/synthetic/lab_reports/syn_0001_complete.png` (run `.venv/bin/python scripts/make_synthetic_lab_reports.py` first if the folder is empty) | `"status": "completed"`, 6 rows (name, value, unit, range), a note that ranges are copied as printed |
| Missing values flagged | `lab_report` | `syn_0002_missing_value.png` | The haemoglobin value shown as `null` with `needs_review: true`, not guessed |
| Skin model | `skin_image` | Any PNG or JPEG of a skin photo under 10 MB, for example a photo from the dataset in `data/raw/PAD-UFES-20/images/` | `"status": "completed"`, a `predicted_class`, six probabilities, the model's test score and a list of limitations |
| Honest refusal without a model | stop the server (`Ctrl+C`), run `unset LUMI_SKIN_MODEL_PATH`, start it again with `./scripts/run_dev.sh`, upload a skin image | the same | `503` and `"model_unavailable"`, with no prediction |
| Security | any | click **Authorize → Logout**, then Execute | `401 unauthorized` |
| Placeholder | `chest_xray` | any PNG | `"status": "not_implemented"`, no prediction (say clearly it is not built) |

## Step 4: show the evidence
```bash
open docs/MODEL_CARD_skin_pad_ufes20.md     # real test results, confusion matrix, limitations
open docs/DATA_GOVERNANCE.md                # which datasets, licences, what is verified and what is pending
open docs/SCOPE_REVIEW.md                   # traceability table and progress log
open data/processed/inspection/pad_ufes_20_report.md   # dataset inspection report (counts only)
```
Optional proof that the API matches the offline evaluation (about 2 minutes):
```bash
.venv/bin/python scripts/check_api_matches_training.py models/skin_pad_ufes20/20261018T072750Z data/raw/PAD-UFES-20/metadata.csv data/raw/PAD-UFES-20/images
```
Expect `identical predicted class for 454 of 454` and one image refused as too large.

## What to say honestly
**Working:** secure API; reading synthetic lab reports; a trained skin-lesion model that answers through the API; honest refusal when no model is set up; dataset inspection; governance records; 218 automated tests.

**Not finished:** chest X-ray analysis; medical question answering (questions are accepted but not answered); explainability heatmaps; PDF reports; OCR accuracy measurement on real reports; any model for children.

**Do not say:** that the model is clinically validated, that it is accurate enough for patients, or that it works for children. The honest numbers are accuracy 0.63 and macro-F1 0.54 on 455 held-out images from adult-dominated data, with a melanoma figure based on only 11 cases.

## Questions to ask your supervisor (also in docs/DATA_GOVERNANCE.md §5.3 and docs/SCOPE_REVIEW.md §8)
1. Is a public CC BY 4.0 dataset acceptable without a separate ethics application?
2. Is an almost entirely adult dataset acceptable for a pediatric project, given 39 under-18 images, all benign nevus?
3. May the commercialisation section stand, given that ImageNet-pretrained weights have an unresolved licence question and HAM10000 is non-commercial?
4. What numeric targets must each pipeline meet (C9)?
5. Which chest X-ray and VQA datasets are approved, and who is the clinical reviewer (C10)?

## If something goes wrong
- **Page won't load:** the server is not running. Check the first terminal for `Application startup complete.`
- **`Address already in use`:** run `pkill -f "uvicorn lumi.main:app"`, then start again.
- **503 `model_unavailable` on a skin image:** the `export LUMI_SKIN_MODEL_PATH=...` line was skipped in this terminal, or the path is wrong.
- **413 on a skin image:** the file is over 10 MB; use a smaller photo.
- **503 `ocr_unavailable`:** Tesseract is missing; run `brew install tesseract`.
