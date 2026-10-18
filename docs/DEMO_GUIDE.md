# LUMI demonstration guide (for you and your supervisor)

Everything below runs on your MacBook. Nothing is sent over the internet. Time needed: about 10 minutes.

## Before you start (once)
Open a terminal in VS Code and run:
```bash
cd "/Users/kidhasia/Desktop/Research Stuff"
.venv/bin/python -m pytest -q          # expect: all tests pass (285 on 2026-10-18)
ls models/skin_pad_ufes20/              # you should see a folder named 20261018T072750Z
```
If `models/` is missing, the trained model is not on this machine; retrain with the command in `docs/MODEL_CARD_skin_pad_ufes20.md` §8 (about 7 minutes).

## Step 1: start LUMI
**Easiest:** in Finder, open the project folder, then `scripts`, and double-click **`start_demo.command`**. A Terminal window opens, the server starts, and your browser opens the demo page by itself. (The first time, macOS may ask you to confirm: right-click the file, choose Open, then Open.)

**Or in the terminal:**
```bash
cd "/Users/kidhasia/Desktop/Research Stuff"
./scripts/run_dev.sh
```
Wait for `Application startup complete.` and leave that window open. The script finds the newest trained model by itself and prints which one it is using. It also pre-fills the throw-away local API key in the page.

## Step 2: open the demo page
Browser: **http://localhost:8000/** (the developer page is still at http://localhost:8000/docs).
At the top you will see three status chips. Skin photo and Lab report should be green ("working") and Chest X-ray grey ("not built yet"). If the skin chip is red, the model was not found (see "If something goes wrong").

## Step 3: show each working feature
Choose what you are uploading, choose a file, click **Analyze**.

| What to show | Choose | File to upload | What you should see |
|---|---|---|---|
| Lab-report reading | Lab report image | `data/synthetic/lab_reports/syn_0001_complete.png` (run `.venv/bin/python scripts/make_synthetic_lab_reports.py` first if the folder is empty) | A table of 6 rows (test, result, unit, range as printed) and a note that LUMI does not judge normal or abnormal |
| Missing values flagged | Lab report image | `syn_0002_missing_value.png` | Haemoglobin shown as "(not found)" with "Check against the original", not guessed |
| Skin model | Skin photo | Any PNG or JPEG under 10 MB from `data/raw/PAD-UFES-20/images/` | The best-matching class, a bar for each of the six probabilities, the model's measured test score, and a Limitations list |
| **Attention map (new)** | Skin photo, with the tick-box "Also show the AI attention map" ticked (it is by default) | the same skin photo | Under the bars: **"Where the model looked"**, the label *"AI attention visualisation — not a diagnosis or proof of correctness."*, your photo next to the same photo with a coloured map (warmer = more influence), a colour scale, and a collapsible list of what the map can and cannot tell you. Untick the box and click Analyze again: the map disappears and the prediction stays the same |
| Honest refusal without a model | Stop the server (`Ctrl+C`), run `LUMI_SKIN_MODEL_PATH=/nonexistent ./scripts/run_dev.sh`, reload the page | the same skin photo | The skin chip turns red and the page says the model is not set up, with no prediction |
| Security | Skin photo | Replace the API key with `wrong` and click Analyze | "401 unauthorized" with a plain-language hint |
| Placeholder | Chest X-ray | any PNG | "Not built yet. No prediction was made." (say clearly it is not built) |

Only use public practice photos and synthetic reports, never a real patient's file.

## Step 4: show the evidence
```bash
open docs/MODEL_CARD_skin_pad_ufes20.md     # real test results, confusion matrix, limitations
open docs/DATA_GOVERNANCE.md                # which datasets, licences, what is verified and what is pending
open docs/SCOPE_REVIEW.md                   # traceability table and progress log
open data/processed/inspection/pad_ufes_20_report.md   # dataset inspection report (counts only)
```
Optional proof that the attention maps come from the real model (about 1 minute; prints a deletion test and a randomisation test):
```bash
.venv/bin/python scripts/check_gradcam_faithfulness.py models/skin_pad_ufes20/20261018T072750Z data/raw/PAD-UFES-20/metadata.csv data/raw/PAD-UFES-20/images
```
Expect: blanking the highlighted areas lowers the predicted class's score by about 0.44, versus about 0.12 for random areas, and maps from a scrambled model correlate at about 0.05.

Optional proof that the API matches the offline evaluation (about 2 minutes):
```bash
.venv/bin/python scripts/check_api_matches_training.py models/skin_pad_ufes20/20261018T072750Z data/raw/PAD-UFES-20/metadata.csv data/raw/PAD-UFES-20/images
```
Expect `identical predicted class for 454 of 454` and one image refused as too large.

## What to say honestly
**Working:** secure API; reading synthetic lab reports; a trained skin-lesion model that answers through the API; honest refusal when no model is set up; dataset inspection; governance records; 285 automated tests.

**Not finished:** chest X-ray analysis; medical question answering (questions are accepted but not answered); attention maps exist only for skin photos, are coarse (8 by 8) and have not been judged by clinicians; PDF reports; OCR accuracy measurement on real reports; any model for children.

**Do not say:** that the model is clinically validated, that it is accurate enough for patients, or that it works for children. Do not say the heatmap shows where the disease is: it shows what influenced the model, and a clinician has not judged whether it is useful. The honest numbers are accuracy 0.63 and macro-F1 0.54 on 455 held-out images from adult-dominated data, with a melanoma figure based on only 11 cases.

## Questions to ask your supervisor (also in docs/DATA_GOVERNANCE.md §5.3 and docs/SCOPE_REVIEW.md §8)
1. Is a public CC BY 4.0 dataset acceptable without a separate ethics application?
2. Is an almost entirely adult dataset acceptable for a pediatric project, given 39 under-18 images, all benign nevus?
3. May the commercialisation section stand, given that ImageNet-pretrained weights have an unresolved licence question and HAM10000 is non-commercial?
4. What numeric targets must each pipeline meet (C9)?
5. Which chest X-ray and VQA datasets are approved, and who is the clinical reviewer (C10)?

## If something goes wrong
- **"Failed to Load Page / ERR_CONNECTION_REFUSED":** the server is not running (it stops when its Terminal window is closed or you press Ctrl+C). Start it again with `start_demo.command` or `./scripts/run_dev.sh` and wait for `Application startup complete.`
- **`Address already in use`:** run `pkill -f "uvicorn lumi.main:app"`, then start again.
- **Skin chip is red / 503 `model_unavailable`:** no trained model was found. Check that `models/skin_pad_ufes20/<run id>/checkpoint.pt` exists (the start script prints which model it uses). If `models/` is missing, retrain (see the model card).
- **413 on a skin image:** the file is over 10 MB; use a smaller photo.
- **503 `ocr_unavailable`:** Tesseract is missing; run `brew install tesseract`.
