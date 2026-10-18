# Chest X-ray plan (research and preparation only)

Written 2026-10-18. **Nothing has been downloaded and no training has been done.** This file is a plan and a record of what was checked. It does not give permission to start. See the approval gate in §6.

Labels used below: **VERIFIED** = read on the official source. **MIRROR-ONLY** = read in a copy hosted by a third party, so the wording is probably right but its origin is unproven. **UNVERIFIED** = reported by secondary sources or remembered, not checked. **ESTIMATE** = my calculation, to be replaced by a measurement.

---

## 1. The dataset: NIH ChestX-ray14

| Question | Answer | Status |
|---|---|---|
| Who released it, and where is the original download? | NIH Clinical Center. The original paper names the download site `https://nihcc.app.box.com/v/ChestXray-NIHCC`. | VERIFIED that the paper names this link (arXiv:1705.02315, read directly). The Box page itself could not be read by my tools (it only returned the word "Box"), so its file list is **unverified** |
| Official paper | Wang et al., "ChestX-ray8: Hospital-scale chest X-ray database and benchmarks on weakly-supervised classification and localization of common thorax diseases", IEEE CVPR 2017, pp. 2097-2106 | VERIFIED |
| What the paper describes | **108,948** frontal-view images from **32,717** patients with **8** disease labels, produced from the radiology reports "using natural language processing" | VERIFIED. This is the earlier 8-label version |
| What the released data is | 14 labels, **112,120** images, **30,805** patients, PNG, 1024 x 1024 | **UNVERIFIED** (reported by several mirrors and papers; I could not read an official page that states it) |
| Usage terms | "The usage of the data set is unrestricted. But you should provide the link to our original download site, acknowledge the NIH Clinical Center and provide a citation to our CVPR 2017 paper." | **MIRROR-ONLY.** Read in a PDF copy of the NIH FAQ hosted in a Hugging Face dataset repository. Its metadata names the author "Wang, Xiaosong (NIH/CC/LDRR)", created 2017-12-14, which fits an NIH origin but does not prove it. The NIH news-release page returned HTTP 403 to my tool |
| Is there a formal licence file? | None found. "Unrestricted, with attribution" is **not a standard licence** (not CC0, not CC BY) | UNVERIFIED. Ask whether it is enough for a thesis and for the proposal's commercialisation section |
| Radiology reports | Not released ("We currently do not have a plan to release the radiological reports") | MIRROR-ONLY |
| Image format | PNG only, no DICOM | MIRROR-ONLY |
| Official split | `train_val_list.txt` and `test_list.txt`, split **by patient** ("All studies from the same patient will only appear in either training/validation or testing set") | MIRROR-ONLY |
| Archives | 12 files `images_001.tar.gz` to `images_012.tar.gz` with published MD5 checksums | MIRROR-ONLY (the checksums were credited to a third party, Utku Ozbulak) |
| Label quality | NLP-mined from reports; **"No finding" does not mean "normal"**; uncertain mentions were labelled "No finding"; the authors say the labels are "meant to be improved by the community" | MIRROR-ONLY. It matches the paper's description of NLP labelling |
| Patient age | Mean about 46 to 47 years (SD about 17) in two secondary reports. **No source gave the number of patients under 18** | UNVERIFIED. The only way to know is to download the small metadata file and count |
| Total size | About 42 to 45 GB according to mirrors | UNVERIFIED. Per-archive sizes unknown |
| Citation to use | Wang X, Peng Y, Lu L, Lu Z, Bagheri M, Summers RM. CVPR 2017, pp. 2097-2106. Plus a link to the original download site and an acknowledgement of the NIH Clinical Center (the three conditions in the FAQ copy) | VERIFIED for the paper; the three conditions are MIRROR-ONLY |

**Privacy.** The FAQ copy says nothing about de-identification, so that is **unverified**. Chest X-rays can show burned-in text, and published research (found by search, not read) reports that patients can in principle be re-identified from chest X-rays. This project will not try to link images to people, will not share images, and will keep them out of Git.

## 2. Is our intended use compatible with the terms?

| Intended use | Compatible? | Why | What is still open |
|---|---|---|---|
| Research prototype and final-year thesis experiments | **Probably yes** | The only terms found say use is unrestricted with attribution | Confirm on the official NIH page; save the text as evidence |
| Showing results to a supervisor and examiners | Probably yes | Same | Cite, link and acknowledge as required |
| The proposal's commercialisation section | **Unclear** | "Unrestricted" is not a defined licence. It may allow commercial use, but nobody has confirmed that for this project | Ask your supervisor and the university whether this wording is enough |
| Any claim about children | **Not supported by what is known** | The dataset is reported to be adult-weighted and the pediatric share is unknown | Count under-18 patients from the metadata file before deciding (§4, step 0) |
| Medical question answering | **Not possible with this dataset alone** | The radiology reports are not released | Use a different dataset for VQA (VQA-RAD, CC0 verified) |

## 3. A pediatric alternative worth knowing about (researched, not chosen)

| Item | Finding | Status |
|---|---|---|
| Dataset | "Large Dataset of Labeled Optical Coherence Tomography (OCT) and Chest X-Ray Images", Mendeley Data, doi:10.17632/rscbjbr9sj.3, published 2018-06-01, institutions UC San Diego and Guangzhou Women and Children's Medical Center | VERIFIED (Mendeley public API) |
| Licence | **CC BY 4.0** | VERIFIED |
| Files | One file, `ZhangLabData.zip`, **8,441,154,111 bytes**. It contains both OCT eye scans and chest X-rays, so the chest X-rays cannot be downloaded alone | VERIFIED size; contents per description |
| Labels | Named "(disease)-(randomized patient ID)-(image number by this patient)"; "split into a training set and a testing set of independent patients" | VERIFIED (record text) |
| Population | Reported by secondary sources as 5,856 X-rays of children aged 1 to 5 from one hospital, pneumonia versus normal. **The Mendeley page itself does not state ages, patient demographics, image selection or ethics approval** | UNVERIFIED |
| Fit | The only pediatric chest source found. It could give a small pediatric experiment, but the task is different (pneumonia versus normal, not 14 findings), the ages (1 to 5) do not cover the project's 3 to 12 range, and one source reported 5,863 images, so counts disagree | Needs the original *Cell* 2018 paper read and a supervisor decision |

## 4. Proposed pilot (to run only after the gate in §6 is passed)

**Goal.** A first honest multi-label chest X-ray model and a measured baseline, small enough to finish in about a day and to repeat.

**Step 0: metadata only, no images (minutes, a few MB).** After approval, download only the small files: the official README or FAQ, the metadata CSV (the mirrors call it `Data_Entry_2017_v2020.csv`; the exact name must be read from the Box folder), `train_val_list.txt` and `test_list.txt`. Record SHA-256 checksums. Then:
1. Read the real CSV header and confirm or correct the column names in the inspector preset `nih_cxr14` (they are MIRROR-ONLY names: `Image Index`, `Finding Labels`, `Follow-up #`, `Patient ID`, `Patient Age`).
2. Run `lumi.data_inspect` for counts, missing values, label prevalence and duplicates.
3. Count patients and images **under 18**, ages that look impossible, and follow-up images per patient.
4. Check that no patient appears in both official lists.
5. Work out which archive(s) hold which patients, so the pilot can use whole patients.
6. Decide go or no-go on the pediatric question with the supervisor.

**Step 1: pilot subset.** Download **one image archive** (`images_001.tar.gz`) and verify its MD5. If the archives are about equal in size, one holds roughly 9,000 to 10,000 images (ESTIMATE from 112,120 / 12). Use only whole patients:
- Pilot **test** set = pilot images whose patients are in the official `test_list.txt`. This keeps it patient-disjoint and comparable with published work.
- Pilot **train / validation** = pilot images whose patients are in `train_val_list.txt`, split **by patient** (about 85% / 15%, fixed seed), saved as a split manifest outside Git.
- Remove exact duplicate files first (the same rule as for skin: keep one copy if labels agree, drop all if they conflict).
- Add a second archive only if the first gives too few positives for the rarer findings.

**Step 2: model.** The same recipe as the skin model: EfficientNet-B0 with transfer learning (Apache-2.0 starting weights; ImageNet caveat from the governance record applies), greyscale images repeated to three channels at 256 px, **multi-label** (one score per finding, sigmoid not softmax, so scores do not add up to 100%), binary cross-entropy with tempered class weights, about 10 epochs, seed recorded, best epoch chosen on validation, **test set touched once**.

**Step 3: metrics (all with patient-level bootstrap 95% intervals).**
- Primary: **AUROC per finding** and macro-AUROC. It is the standard measure for this dataset and does not depend on a threshold.
- **AUPRC with the prevalence shown**, because most findings are rare.
- Sensitivity, specificity and F1 at thresholds **chosen on the validation set only**.
- A finding with too few positive test images (proposed: fewer than 30; the supervisor should confirm) is reported as "too few to evaluate", not given a number.
- Calibration is not claimed. Scores are not probabilities.
- Baseline: chance (AUROC 0.5). Compare with published numbers **only after reading them in the original papers**; none are quoted here.
- No numeric pass mark is invented. Targets must come from the supervisor (scope review C9).

**Step 4: checks before anything is shown to users.** The Grad-CAM deletion and randomisation checks used for the skin model, on a chosen finding. Test the API against the offline evaluation. Check logs for leaks. Only then replace the placeholder, change the interface page from "In development", and update the documents.

**Compute (measured and estimated).** Your Mac (Apple M5, 16 GB, 311 GB free disk) trained the skin model at roughly 50 images per second at 256 px, about 25 to 30 seconds for 1,362 images (MEASURED).
- Training: about 9,500 images / 50 per second = **about 3 minutes per epoch, about 30 minutes for 10 epochs** (ESTIMATE).
- Memory: an in-memory cache of 10,000 greyscale 256 px images is about 0.65 GB (ESTIMATE).
- Resizing 10,000 PNGs of 1024 x 1024: roughly 5 to 10 minutes (ESTIMATE, to be measured).
- Disk for one archive: unknown until the file size is read; the full dataset is reported at 42 to 45 GB, which would fit but is not needed.
- No cloud GPU is needed. Nothing would leave the Mac.

**Risks to state in the thesis.** Noisy NLP labels; "No finding" is not "normal"; shortcuts such as chest drains or text markers that correlate with labels; hospital-specific images; adult-weighted patients; patients with several follow-up images (hence patient-level splits); no pediatric evidence unless Step 0 shows it.

## 5. After a model exists

Add a `ChestXrayPipeline` that returns one score per finding (not a single "predicted class"), reuse the Grad-CAM engine for a **user-chosen finding**, keep the same error handling and the same 503 "model not set up" behaviour, add tests with synthetic images, and only then turn the Chest X-ray page from "In development" into a working page. Until all of that is done and tested, the page and the API placeholder stay as they are, and the interface page says so.

## 6. Approval gate (all must be ticked before any download or training)

| # | Requirement | Owner | Status |
|---|---|---|---|
| 1 | Read the **official** NIH terms yourself (the Box folder's README or FAQ and the NIH page) and save the exact text, URL and date in `docs/DATA_GOVERNANCE.md` | You | **Not done** |
| 2 | Supervisor approves ChestX-ray14 as the chest dataset (the panel asked you to "gather and validate the required data from appropriate sources") | Supervisor | **Not done** |
| 3 | Supervisor or university confirms whether "unrestricted use with attribution" is enough for the commercialisation section | Supervisor | **Not done** |
| 4 | Confirm that a public, de-identified dataset needs no separate ethics application (governance question 2) | Supervisor / ethics board | **Not done** |
| 5 | Decide how to handle the pediatric gap: accept an adult-weighted dataset with the limitation stated, or also pursue a pediatric dataset (§3) | Supervisor | **Not done** |
| 6 | Agree the numeric targets and the "too few to evaluate" rule (scope review C9) | Supervisor | **Not done** |
| 7 | Start with Step 0 (metadata only), then review its findings before Step 1 | You and the assistant | **Not done** |

## 7. Questions for your supervisor
1. May we use NIH ChestX-ray14 for the chest X-ray component, starting with a one-archive pilot?
2. Is "unrestricted, with a link, acknowledgement and citation" acceptable for the thesis and for the commercialisation section?
3. Is a public, de-identified dataset acceptable without our own ethics application?
4. The dataset is adult-weighted and its pediatric share is unknown. Is that acceptable if the limitation is stated, or should we also pursue a pediatric dataset such as the Guangzhou children's X-rays (CC BY 4.0, 8.4 GB download)?
5. What numeric targets and minimum numbers of positive cases do you want for each finding?
6. Which dataset should be used for medical question answering, given that ChestX-ray14 has no reports? (VQA-RAD is CC0 by the OSF record, but is adult radiology.)
