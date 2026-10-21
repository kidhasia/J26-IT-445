# LUMI demonstration guide (for you and your supervisor)

Everything below runs on your MacBook. Nothing is sent over the internet. Time needed: about 10 minutes.

## Before you start (once)
Run `./scripts/demo_preflight.sh` first. It only reads things and must end with `READY`. A backup plan for failures is in `docs/SUBMISSION_PLAN.md` §4.

Open a terminal in VS Code and run:
```bash
cd "/Users/kidhasia/Desktop/Research Stuff"
.venv/bin/python -m pytest -q          # expect: all tests pass (485 on 2026-10-18)
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

## Step 2: open the interface
Browser: **http://localhost:8000/** (the developer page is still at http://localhost:8000/docs).

You will see a menu on the left (on a phone it runs across the top) with six pages: **Overview, Skin Analysis, Lab Reports, Ask a question, Chest X-ray, About LUMI**. At the top right, a green **"Server connected"** label and an **API key** button (the key is already filled in for local use).

On **Overview**, the tool cards show their real status taken from the server: Skin Analysis and Lab Reports are green; Chest X-ray says **In development** and Medical questions says **Small prototype** (it opens the **Ask a question** page). If Skin Analysis shows "Model not set up" in red, the model was not found (see "If something goes wrong").

## Step 3: show each working feature
| What to show | Where | File to upload | What you should see |
|---|---|---|---|
| Skin model | **Skin Analysis**: drag a photo onto the drop area or click **browse**, then **Analyze photo** | Any PNG or JPEG under 10 MB from `data/raw/PAD-UFES-20/images/` | The highest-scoring class, a bar for each of the six model scores (labelled as *not* calibrated probabilities), the model's measured test score, a Limitations list and the clinical boundary notice |
| Attention map | Same page, with **Show attention map (Grad-CAM)** switched on (it is by default) | the same photo | **"Attention map (experimental)"** under the label *"AI attention visualisation — not a diagnosis or proof of correctness."*, your photo beside the same photo with a coloured map (warmer = more influence), a colour scale, and a collapsible list of what the map can and cannot tell you. Switch it off and analyze again: the map disappears and the scores stay the same |
| Lab-report reading | **Lab Reports**, then **Read report** | `data/synthetic/lab_reports/syn_0001_complete.png` (run `.venv/bin/python scripts/make_synthetic_lab_reports.py` first if the folder is empty) | A yellow "Check every value against the original report" box and a table of 6 rows (test, result, unit, range as printed), each marked **Parsed** |
| Missing values flagged | **Lab Reports** | `syn_0002_missing_value.png` | Haemoglobin's result shown as **Not found** with "Check against the original", not guessed |
| Questions about a result | **Ask a question**, after you have analysed a photo and a report | (none; it uses the results already on screen) | Pick the lab result and ask "Which lab values were not found?" and "What was the reported haemoglobin value?"; pick the skin result and ask "What limitations apply to this result?". Then ask "Is this cancer?" and "Is my haemoglobin normal?": both are **refused** with "I cannot answer this from the available evidence.". The answer shows an evidence-not-verified warning |
| Floating helper (optional) | **Ask LUMI** button, bottom-right of any page | (none) | A small panel with quick actions. *LUMI documents* mode quotes project documents with citations; *My result* mode reads back facts from a skin or lab result you already made; unsafe or unsupported questions get the exact refusal. Labelled *Guide* messages are fixed help text, not answers. See `docs/RAG_DEMO_GUIDE.md` section 7 |
| Retrieval prototype (optional) | **Reference search** | (none) | Quoted passages from LUMI's own project documents with citations; an unrelated question is refused. Full guide, sample questions and limits: `docs/RAG_DEMO_GUIDE.md`. Extractive only, not generative, not medical advice |
| Chest X-ray is unfinished | **Chest X-ray** | (nothing to upload) | A page that says it is **In development**, that there is no chest X-ray model, and that it makes no predictions. It has no upload control on purpose |
| Limits and data | **About LUMI** | | What works, the PAD-UFES-20 dataset, the model's measured score from the server, and the limitations, including that it is not validated for children |
| Honest refusal without a model | Stop the server (`Ctrl+C`), run `LUMI_SKIN_MODEL_PATH=/nonexistent ./scripts/run_dev.sh`, reload | the same skin photo | Overview shows "Model not set up" in red, and Skin Analysis explains that no analysis was done |
| Bad file | **Skin Analysis** | a `.txt` file | A clear message that the file type is not supported (checked in the browser before anything is sent) |
| Security | Click **API key**, replace the key with `wrong`, then analyze | any photo | "The API key was not accepted" with a plain-language hint and the key box open |

Only use public practice photos and synthetic reports, never a real patient's file.

## Step 4: show the evidence
```bash
open docs/MODEL_CARD_skin_pad_ufes20.md     # real test results, confusion matrix, limitations
open docs/DATA_GOVERNANCE.md                # which datasets, licences, what is verified and what is pending
open docs/SCOPE_REVIEW.md                   # traceability table and progress log
open data/processed/inspection/pad_ufes_20_report.md   # dataset inspection report (counts only)
```
Optional proof that the interface works in a real browser (about 1 minute; needs Google Chrome; it drives every page and flow, fakes server failures, and checks keyboard use, layout at four screen widths and that nothing is requested from other websites):
```bash
.venv/bin/python scripts/ui_smoke_test.py --skin-image data/raw/PAD-UFES-20/images/imgs_part_1/PAT_100_393_595.png --lab-image data/synthetic/lab_reports/syn_0001_complete.png
```
Expect `97 of 97 browser checks passed`. Screenshots are saved in `data/processed/ui_smoke/` (not in Git).

Optional proof of the lab-report reading accuracy (about 10 seconds; needs Tesseract; synthetic reports only):
```bash
.venv/bin/python -m lumi.eval.ocr_eval
```
Expect `Reports evaluated: 3`, `Reference text verified against every image: yes`, LUMI pipeline character error about 1.26% and word error about 11.67%, plain Tesseract about 1.10% and 10.00%. Say plainly that this is **three clean synthetic reports**, that every error was a dropped space beside a hyphen or "<", and that it does not show how the OCR performs on real reports. Full report: `docs/OCR_EVALUATION.md`.

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
**Working:** secure API; reading synthetic lab reports; a trained skin-lesion model that answers through the API; honest refusal when no model is set up; dataset inspection; governance records; 368 automated tests and 80 real-browser checks.

**Not finished:** chest X-ray analysis; image-based medical question answering (only a small rule-based `/api/v1/ask` exists: it answers from a result you already produced, never from the image, and refuses everything else; it has an **Ask a question** page); attention maps exist only for skin photos, are coarse (8 by 8) and have not been judged by clinicians; PDF reports; OCR accuracy measurement on real reports; any model for children.

**Do not say:** that the model is clinically validated, that it is accurate enough for patients, or that it works for children. Do not say the heatmap shows where the disease is: it shows what influenced the model, and a clinician has not judged whether it is useful. The honest numbers are accuracy 0.63 and macro-F1 0.54 on 455 held-out images from adult-dominated data, with a melanoma figure based on only 11 cases.

## Questions to ask your supervisor (also in docs/DATA_GOVERNANCE.md §5.3 and docs/SCOPE_REVIEW.md §8)
1. Is a public CC BY 4.0 dataset acceptable without a separate ethics application?
2. Is an almost entirely adult dataset acceptable for a pediatric project, given 39 under-18 images, all benign nevus?
3. May the commercialisation section stand, given that ImageNet-pretrained weights have an unresolved licence question and HAM10000 is non-commercial?
4. What numeric targets must each pipeline meet (C9)?
5. Which chest X-ray and VQA datasets are approved, and who is the clinical reviewer (C10)? The chest X-ray research, approval gate and questions are in `docs/CHEST_XRAY_PLAN.md`; nothing has been downloaded.

## If something goes wrong
- **"Failed to Load Page / ERR_CONNECTION_REFUSED":** the server is not running (it stops when its Terminal window is closed or you press Ctrl+C). Start it again with `start_demo.command` or `./scripts/run_dev.sh` and wait for `Application startup complete.`
- **`Address already in use`:** run `pkill -f "uvicorn lumi.main:app"`, then start again.
- **Skin chip is red / 503 `model_unavailable`:** no trained model was found. Check that `models/skin_pad_ufes20/<run id>/checkpoint.pt` exists (the start script prints which model it uses). If `models/` is missing, retrain (see the model card).
- **"That file is ... over the 10 MB limit":** use a smaller photo. A few full-resolution dataset photos are larger than 10 MB.
- **The page looks unstyled or does nothing:** the server is running an old copy. Stop it with `Ctrl+C` and start it again with `start_demo.command`.
- **503 `ocr_unavailable`:** Tesseract is missing; run `brew install tesseract`.
