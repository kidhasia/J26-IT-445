# LUMI Dataset Governance Checklist

Project J26-IT-445, component IT23153318. Created 2026-10-16.

**Status of every dataset below: NOT downloaded, NOT accessed, licence NOT verified, NO approval assumed.**

Details about each dataset come from published papers and general knowledge. **Before you rely on any of them, check every point against the official source.** Licences, access rules and hosting locations change. Fill in the "Verified on / by" fields yourself after reading the official pages.

Related: [SCOPE_REVIEW.md](SCOPE_REVIEW.md) (C5, C6, C7, C9, C10, C11), [templates/DATA_CARD_TEMPLATE.md](templates/DATA_CARD_TEMPLATE.md).

---

## 1. Universal checklist (do this for every dataset before downloading)

- [ ] Find the **official** source: the dataset paper, plus the hosting page it names. Mirrors such as Kaggle copies are not the official source.
- [ ] Read the licence or terms of use in full. Record the exact licence name and version, plus the URL and date read.
- [ ] Check **commercial-use** restrictions. The proposal has a commercialisation section (§6), and "non-commercial" licences may block that.
- [ ] Check **redistribution** rules: may you share the images, or model weights trained on them?
- [ ] Check whether a **data use agreement**, registration or training certificate is required. If so, complete it yourself; nobody may do it on your behalf.
- [ ] Record the **exact version** (release, year, DOI) and file checksums after downloading.
- [ ] Write the **citation** text required by the dataset owners.
- [ ] Get supervisor confirmation that the dataset is appropriate. The panel asked you to "gather & validate the required data from appropriate sources".
- [ ] Store data **outside Git**, under `data/raw/` (already ignored). See §4.
- [ ] Fill in a data card (template in `docs/templates/`) **before** training on the data.
- [ ] Define train/val/test splits **by patient or lesion**, not by image, and save the split files before any model comparison (PROP §3.5).

---

## 2. Candidate datasets

### 2.1 HAM10000 (skin lesions)

| Item | Details (verify every row) |
|---|---|
| Official source to verify | Tschandl, Rosendahl & Kittler, *Scientific Data* 5:180161 (2018). The paper points to the Harvard Dataverse record (DOI 10.7910/DVN/DBW86T). It was also used in the ISIC 2018 challenge (Task 3). |
| Licence / terms to review | **Verified 2026-10-16** from the official Dataverse record (via its public metadata API; no data downloaded): the terms of use name the *Creative Commons Attribution-NonCommercial 4.0 International Public License*, which allows sharing and adapting "for NonCommercial purposes only". Models trained on it may therefore not be usable commercially; this matters for PROP §6 (ask your supervisor, §3 question 12). Record version 4, released 2023-02-07. Re-read the live page yourself before relying on this. |
| Files listed on the official record | `HAM10000_images_part_1.zip` (5000 JPEGs, ~1.4 GB), `HAM10000_images_part_2.zip` (5015 JPEGs, ~1.4 GB), `HAM10000_metadata.tab` (**tab-separated**), lesion segmentations zip, plus ISIC 2018 Task 3 test images and ground truth ("in the same format as the HAM10000 metadata"). Of the metadata columns, the official page names only `lesion_id`; the other names (`image_id`, `dx`, `dx_type`, `age`, `sex`, `localization`) come from secondary sources, so check them against the real header (the inspector does this). |
| Modality | **Dermatoscopic** images (taken through a dermatoscope), RGB JPEG. **Not** ordinary phone photos. |
| Label structure | One diagnosis per image across 7 classes: `akiec`, `bcc`, `bkl`, `df`, `mel`, `nv`, `vasc`. Metadata includes `lesion_id`, `image_id`, `dx`, `dx_type` (how the diagnosis was confirmed: histopathology, follow-up, expert consensus, confocal), `age`, `sex`, `localization`. |
| Known biases / limitations | Heavy class imbalance (`nv` is the large majority). Collected mainly from Austrian and Australian practices, so lighter skin tones dominate. Mostly adult patients (check the `age` distribution yourself). Pigmented lesions only, which is not the common pediatric skin conditions (C5, C6). Dermatoscopic images differ from the phone photos LUMI will receive. Several images can show the **same lesion**. |
| Patient-level identity risk | Low for close-up dermatoscopic images, but the metadata (age, sex, body site) combined with rare diagnoses could narrow identity. Never try to link records to people. |
| Intended task in LUMI | Skin-lesion pipeline baseline (SO2, FR3). |
| Leakage warning | Split by **`lesion_id`**, never by `image_id`, or the same lesion lands in both train and test and inflates results. |
| Citation requirement | Cite the *Scientific Data* paper. Check the Dataverse page for any extra acknowledgement text. |

### 2.2 ISIC Archive / ISIC challenge datasets (skin lesions)

| Item | Details (verify every row) |
|---|---|
| Official source to verify | International Skin Imaging Collaboration (ISIC) archive and challenge pages. Each yearly challenge (2016–2020, later ones) has its own dataset and paper. |
| Licence / terms to review | **Licences can differ per image** in the archive (e.g. CC0, CC BY, CC BY-NC). Challenge datasets have their own terms. Record the licence for the exact subset you use, and check attribution requirements per image. |
| Modality | Mostly dermatoscopic; some subsets include clinical (non-dermatoscopic) close-ups. Check which. |
| Label structure | Varies by challenge: diagnosis classes, benign/malignant, segmentation masks. Some later challenges include patient-level metadata. |
| Known biases / limitations | The same skin-tone and adult-population concerns as HAM10000. **Overlap**: HAM10000 is part of ISIC 2018, so combining them can create duplicates across splits. Imaging-centre differences can let models learn shortcuts (rulers, ink marks, vignetting). |
| Patient-level identity risk | As for HAM10000. Some subsets include patient IDs for grouping; use them only for splitting. |
| Intended task in LUMI | Extra skin data or an external test set, **only if** the supervisor agrees and licences allow. |
| Citation requirement | Cite the specific challenge paper(s) and follow the archive's attribution rules. |

### 2.3 Chest X-ray: NIH ChestX-ray14 (the "ChestX-ray8" family named in the proposal)

| Item | Details (verify every row) |
|---|---|
| Official source to verify | Wang et al., "ChestX-ray8…", CVPR 2017 (PROP ref [3]). Released by the **NIH Clinical Center**. Download from the NIH-hosted page listed in the official README; Kaggle copies are mirrors. |
| Licence / terms to review | The NIH README states its terms of use and the required acknowledgement. **Read it and record it exactly**; do not rely on a mirror's licence label. |
| Modality | Frontal chest radiographs, PNG (converted from DICOM; the original DICOM headers are not included). |
| Label structure | Multi-label: 14 findings + "No Finding", **text-mined from radiology reports by NLP**, so labels are weak and noisy (PROP §3.2 acknowledges this). Metadata includes patient ID, age, sex, view position and follow-up number. Bounding boxes exist for a small subset only. Official train/val vs test split lists are provided. |
| Known biases / limitations | Label noise from NLP extraction. Mostly adult patients from one US hospital (C5). Contains many follow-up images per patient. Known shortcut risks (e.g. chest drains, which appear after treatment, can correlate with labels). Not pediatric. |
| Patient-level identity risk | Images are de-identified, but X-rays can contain **burned-in text** (markers, dates). Patient IDs exist; use them only for splitting. |
| Intended task in LUMI | Chest X-ray pipeline baseline (SO2, FR3). |
| Leakage warning | Split by **patient ID**. Use the official split lists if you want results comparable with published work. |
| Size note | The full set is very large (tens of GB). Your Mac has room, but agree with your supervisor whether a documented subset is acceptable. |
| Citation requirement | Cite Wang et al. 2017 and include the NIH Clinical Center acknowledgement from the README. |
| Secondary-source details (NOT checked against the official README) | Third-party mirrors report metadata columns `Image Index`, `Finding Labels` (pipe-separated), `Follow-up #`, `Patient ID`, `Patient Age`, `Patient Gender`, `View Position`; official split lists `train_val_list.txt` (86,524 images, 28,008 patients) and `test_list.txt` (25,596 images, 2,797 patients) with no shared patients; one mirror says the metadata file was reissued as `Data_Entry_2017_v2020.csv`. Treat all of this as unverified until you read the official README. |

**Other chest X-ray candidates (not in the proposal; only with supervisor approval, so scope isn't silently expanded):**

| Dataset | Why it might matter | Governance flag |
|---|---|---|
| CheXpert (Stanford) | Widely used benchmark | Registration and a research-use agreement; read the commercial-use terms |
| MIMIC-CXR (PhysioNet) | Large, with free-text reports | **Credentialed access**: training course + data use agreement in your own name; strict no-redistribution rules |
| Pediatric pneumonia CXR set (Kermany et al., *Cell* 2018, Guangzhou Women and Children's Medical Center) | One of the few public **pediatric** X-ray sets (relevant to C5) | Verify the licence on its official host; known issues with how test/validation splits were defined in some mirrors |

### 2.4 Medical VQA: VQA-Med (ImageCLEF) and compatible sets

| Item | Details (verify every row) |
|---|---|
| Official source to verify | ImageCLEF VQA-Med task overview papers (2019 edition is PROP ref [1]) and the official release pages named in those papers. Each year (2018–2021) is a different dataset. |
| Licence / terms to review | ImageCLEF datasets may require **registration or an end-user agreement**. Check each edition. Images may come from third-party sources with their own terms. |
| Modality | Radiology images (CT, MRI, X-ray, ultrasound) with English question–answer pairs. |
| Label structure | 2019 edition: questions in categories such as modality, plane, organ system and abnormality, with short reference answers and official evaluation metrics (accuracy, BLEU). Check the exact edition you use. |
| Known biases / limitations | Many questions were **generated semi-automatically** from captions, so the wording is formulaic and unlike real parent or clinician questions. Answer distributions are skewed. Adult radiology dominates. **No dermatoscopy and no lab reports**, so it only covers part of LUMI's VQA scope. Not pediatric. |
| Patient-level identity risk | Low (published teaching or case images), but check for burned-in text. |
| Intended task in LUMI | External benchmark for image–question answering (PROP Table 5, "VQA-Med or a compatible benchmark"). |
| Citation requirement | Cite the overview paper for the edition used, and follow ImageCLEF's citation rules. |

"Compatible" alternatives the proposal allows, each needing its own licence check and supervisor approval: **VQA-RAD** (Lau et al., *Scientific Data* 2018, clinician-written questions), **SLAKE** (Liu et al. 2021), **PathVQA** (pathology; probably out of scope).

### 2.5 Laboratory reports

| Option | Status | Rules |
|---|---|---|
| **A. Synthetic reports** (`lumi/eval/synthetic_lab_reports.py`) | **In use.** No approval needed: no real person is described | Every image carries the "SYNTHETIC … NOT REAL PATIENT DATA" banner. Values and ranges are placeholders, **not clinical reference values**. Ground truth is saved next to each image for CER/WER. Limitation: clean, single-layout, computer-drawn text, which is easier than real photographed reports. Results on synthetic data must be reported as such. |
| **B. De-identified real reports** from local doctors or clinics | **Blocked**: requires ethics approval (C11), consent and a data-sharing agreement (TAF p.10) | See §3 for questions. Only after approval: de-identify **before** the data reaches your laptop, keep it out of Git and out of any cloud service not covered by the approval, and log who accessed what. |
| C. Public de-identified lab-report datasets | None identified in the proposal | Do not search scraped "sample reports" from the web: their origin and consent are unknown. |

**What counts as identifying in a lab report** (all of it must be removed in option B): name, date of birth, age when combined with other data, ID or NIC numbers, hospital or medical record numbers, addresses, phone numbers, emails, dates of sample and report, names of doctors, laboratory staff or the referring clinic, **barcodes and QR codes**, signatures, and photos. Also check **EXIF metadata** in phone photos, which can include GPS location and device information.

---

## 3. Questions to ask your supervisor before using any clinical data

**Ethics and approval**
1. Has the ethics application (IRB/ERB) been submitted? What is its reference number and status? Which data types and sources does it cover?
2. Is approval needed even for **public** datasets, or only for local clinical data?
3. Who is the named clinical partner? Is there a **signed data-sharing agreement**, and who signed it?
4. Is the external medical supervisor confirmed in writing (C10)? Who will act as clinical reviewer?

**Consent and children**
5. How will parental/guardian consent be obtained and recorded? Is **child assent** also needed for older children?
6. Can consented data be used for model training, or only for evaluation?

**De-identification and storage**
7. Who de-identifies the data: the clinic before handover, or me? Which standard should be followed?
8. Which laws and policies apply: Sri Lanka's Personal Data Protection Act No. 9 of 2022, SLIIT policy, the hospital's own rules? (The TAF mentions HIPAA/GDPR "principles"; confirm what is actually binding.)
9. Where may clinical data be stored: my laptop (encrypted?), a SLIIT server, or a named cloud provider? May it be uploaded to Google Colab or similar GPU services?
10. How long may data be kept, and how must it be deleted at the end of the project?
11. Who else on the team may access it?

**Public datasets**
12. Is a **non-commercial** licence (e.g. HAM10000, if confirmed) acceptable, given the proposal's commercialisation section?
13. Which chest X-ray dataset is approved, full or a documented subset? Should a pediatric set be added (C5)?
14. Which VQA dataset and edition should be the benchmark?
15. Is it acceptable to evaluate the "pediatric" claim on adult datasets, with the limitation clearly stated (C5)?

**Reporting**
16. What numeric targets must each pipeline meet (C9)?
17. Can results on synthetic lab reports be reported as evidence, and with what wording?

---

## 4. Data that must NEVER be committed to Git

Git keeps everything forever: deleting a file later does **not** remove it from history, and pushing to GitHub publishes it.

| Never commit | Why | Enforced by |
|---|---|---|
| Any real patient data: images, reports, scans, DICOM files, extracted text, spreadsheets | Privacy, consent, law | `.gitignore` (`data/` except docs, `*.dcm`) + `tests/test_repo_hygiene.py` |
| Downloaded public datasets (HAM10000, ISIC, ChestX-ray14, VQA-Med…) | Licences often forbid redistribution; size | `.gitignore` `data/` |
| Data split files listing real patient or lesion IDs | Can reveal membership of a restricted dataset | Keep under `data/`; record their checksums in the data card instead |
| Trained model weights (`*.pt`, `*.pth`, `*.ckpt`, `*.safetensors`, `*.onnx`, `*.h5`) | May memorise training data; licences may restrict sharing weights; size | `.gitignore` + hygiene test |
| API keys, passwords, `.env` files, consent forms, data-sharing agreements | Security, personal details | `.gitignore` + hygiene test |
| Server logs from real usage | May contain request metadata | `.gitignore` (`*.log`, `logs/`) |
| Your signed TAF/proposal PDFs | Signatures and personal details | `.gitignore` (`/*.pdf`) |

What **may** be committed: code, tests, these governance documents, completed data cards (without patient-level rows), the synthetic-report **generator** (the images are regenerated on demand), and aggregate evaluation results.

If something sensitive is ever committed by mistake: **stop, don't push**, and ask your supervisor. Removing it from history needs special tools, and if it has already been pushed, the data must be treated as exposed.

---

## 5. Acquisition log (updated 2026-10-18)

Legend: **VERIFIED** = read on the official source on the date shown. **UNVERIFIED** = only seen via a mirror, a search summary or memory. **PENDING** = needs your supervisor or another party. Nothing in this section is legal advice.

### 5.1 Status at a glance

| Dataset | Used for | Licence | Downloaded? | Use status |
|---|---|---|---|---|
| **PAD-UFES-20** v1 | Skin-lesion classifier (SO2/FR3) | CC BY 4.0 (VERIFIED) | **Yes**, 2026-10-18, and inspected | **In use for the research prototype.** Supervisor confirmation PENDING (see §5.3) |
| HAM10000 | Skin (alternative) | CC BY-NC 4.0 (VERIFIED 2026-10-16) | No | **On hold.** Non-commercial; conflicts with the proposal's commercialisation section until your supervisor decides |
| NIH ChestX-ray14 | Chest X-ray | **Terms read in a mirror's copy of the NIH FAQ only** ("unrestricted", but link to the original site, acknowledge the NIH Clinical Center and cite the CVPR 2017 paper). The official NIH pages could not be read by my tools. "Unrestricted" is not a standard licence | **No** (reported at about 42-45 GB, unverified) | **Not started. Approval gate not passed.** See `docs/CHEST_XRAY_PLAN.md` |
| VQA-RAD | Medical VQA | CC0 1.0 Universal (VERIFIED via the OSF API, node 89kps, 2026-10-18) | No | **Candidate**, not yet used. Small (315 images). Dataset contents and size not yet inspected |
| Synthetic lab reports | OCR | Created by the project | Generated locally | In use (see data_cards/synthetic_lab_reports.md) |

### 5.2 PAD-UFES-20: the dataset actually used

| Item | Record |
|---|---|
| Official source | Mendeley Data, doi:10.17632/zr7vgbcyr2.1, version 1, published 2020-07-07. Read through the Mendeley public API (2026-10-18) |
| Licence | **CC BY 4.0** (name and URL given by the record: creativecommons.org/licenses/by/4.0). Permits sharing and adapting, including commercially, **with attribution** |
| Access | Public file links, no login and no click-through licence |
| Files (names and byte sizes match the official listing exactly) | `imgs_part_1.zip` 1,245,184,680; `imgs_part_2.zip` 1,126,646,990; `imgs_part_3.zip` 1,220,565,093; `metadata.csv` 316,209 |
| SHA-256 of the downloaded files | part_1 `0ab44f60938bf57445e12f518a8878954cc734e6b0aec6d01194e2d26b4b2dca`; part_2 `e2d9a3cbd58e823f5ae33163c48643e7d1b54ae3f9e145f01f8e9f16a363a60b`; part_3 `ecc4ef10143a43e1d01cb736773148607a78b530417eb76f2c38ad24bf5d0d2c`; metadata `14d145235cedb022548257acb0d84dcd949e2c916f65d2baa7c38ed5339e9527` |
| Integrity | All three zips pass `unzip -t`. 2,298 PNG files extracted; 2,298 metadata rows; every id matched a file |
| Storage | About 3.6 GB zips + about 3.6 GB extracted, under `data/raw/PAD-UFES-20/` (ignored by Git). Originals never modified |
| Citation (VERIFIED from the paper) | Pacheco AGC, et al. "PAD-UFES-20: A skin lesion dataset composed of patient data and clinical images collected from smartphones." *Data in Brief* 32:106221 (2020). doi:10.1016/j.dib.2020.106221. Also cite the Mendeley dataset DOI and give attribution as CC BY 4.0 requires |
| Content | Smartphone clinical photos (PNG, varying sizes, 147 to 3,476 px per side, nearly all square), 6 diagnoses: ACK 730, BCC 845, MEL 52, NEV 244, SCC 192 (includes Bowen's disease), SEK 235. About 58% biopsy-proven (from the record). 1,373 patients, 1,641 lesions, 2,298 images. Matches the inspector's counts exactly |
| Ethics (stated by the dataset authors, not checked by me) | Collected by a UFES (Brazil) program with university ethics-committee and Plataforma Brasil approval and patient consent |
| Patient/lesion identifiers | `patient_id`, `lesion_id`, `img_id` present. **Splits are by patient_id**; verified in code with a leakage check |

**Findings from the inspector and follow-up checks (real data, 2026-10-18):**

- 0 corrupt images. All 1,440 RGBA images are fully opaque (no transparency).
- **15 duplicate image files**, all within a single patient. In **12 of the 15 pairs the same file carries two different diagnosis labels**. Rule applied (fixed before training): drop all copies when labels conflict (24 images), keep one copy when they agree (3 images dropped). **2,271 images remain.** Source data unchanged.
- **Almost no children:** ages run 6 to 94, median 62. Only **39 of 2,298 images (23 of 1,373 patients) are from patients under 18, and all 39 are labelled NEV (benign nevus).** There is no pediatric melanoma/BCC/SCC/ACK/SEK data. **This is a serious limitation for a pediatric project (scope review C5).**
- About 35% of the clinical-history columns (smoking, drinking, Fitzpatrick type, diameter, etc.) are empty. They are not used by the model.
- Severe class imbalance (MEL 2.3%), so the held-out test set contains few melanoma images and its per-class numbers are noisy.

### 5.3 Approvals: what is NOT yet settled (PENDING, ask your supervisor)

1. Is a public CC BY 4.0 dataset that was de-identified by its authors acceptable without your own ethics application? (governance question 2 in §3.)
2. Is a skin-cancer dataset of mostly adult patients acceptable for a *pediatric* system, given only 39 benign-nevus images from under-18s (C5)?
3. The pretrained starting weights (`timm/efficientnet_b0.ra_in1k`, Hugging Face model card read 2026-10-18) are licensed **Apache-2.0**, public and not gated, but were trained on **ImageNet-1k**, whose own terms are research-oriented. Whether those terms affect commercial use of derived weights is **unresolved**; this matters for the commercialisation section.
4. Final approval to present the trained model as thesis evidence.

### 5.4 Other candidates researched but not downloaded

| Candidate | What is known | Open points |
|---|---|---|
| NIH ChestX-ray14 | Original data is hosted by the NIH Clinical Center on Box (`nihcc.app.box.com/v/ChestXray-NIHCC`, the link given in the original paper, **verified**); the Box page itself could not be read by my tools. Full research record, approval gate and pilot plan: `docs/CHEST_XRAY_PLAN.md` | Read the official terms yourself and save them here. The pediatric share is unknown until the metadata file is counted |
| VQA-RAD | OSF doi:10.17605/OSF.IO/89KPS, CC0 1.0 (VERIFIED). A mirror reports 315 images and 2,248 question-answer pairs; the paper reports 3,515 questions; the difference is unresolved | Check contents on the OSF page; adult radiology only, so pediatric relevance is limited |
| ISIC Archive (per-image CC0, CC-BY or CC-BY-NC) | Licence is set per image; the AWS Open Data registry lists an anonymous S3 bucket. A commercial-use-compatible subset could be built by filtering to CC0/CC-BY | Not investigated further today; check each image's licence |

---

## 6. Chest X-ray research (2026-10-18; nothing downloaded)

Full detail, the approval gate and the pilot plan are in [CHEST_XRAY_PLAN.md](CHEST_XRAY_PLAN.md). Summary of what is verified and what is not:

| Item | Status |
|---|---|
| Original paper (arXiv:1705.02315, CVPR 2017): 108,948 frontal images, 32,717 patients, 8 labels mined from radiology reports with NLP; it names `https://nihcc.app.box.com/v/ChestXray-NIHCC` as the download site | **VERIFIED** (read directly). This is the earlier 8-label version |
| Released dataset: 14 labels, 112,120 images, 30,805 patients, PNG 1024 x 1024 | **UNVERIFIED** (mirrors and secondary papers only) |
| Terms: usage "unrestricted", but give the link to the original download site, acknowledge the NIH Clinical Center, cite the CVPR 2017 paper | **MIRROR-ONLY.** Read in a PDF copy of the NIH FAQ in a Hugging Face dataset repository (PDF author field "Wang, Xiaosong (NIH/CC/LDRR)", created 2017-12-14). NIH's own news-release page returned HTTP 403 and the Box page could not be read |
| No formal licence file was found | "Unrestricted with attribution" is not CC0 or CC BY; whether it covers the proposal's commercialisation section is **unresolved** |
| Radiology reports are not released; PNG only; official patient-level split lists exist; 12 image archives with published MD5 checksums; "No finding" is not "normal"; labels are noisy | MIRROR-ONLY |
| Patients under 18 | **Unknown.** No source gave a count. Only the small metadata file can answer it |
| Re-identification | Chest X-rays can in principle be matched to individuals (secondary report found by search, not read). This project will not attempt linking and will not share images |

**Pediatric alternative researched, not chosen:** "Large Dataset of Labeled Optical Coherence Tomography (OCT) and Chest X-Ray Images", Mendeley Data doi:10.17632/rscbjbr9sj.3 (UC San Diego and Guangzhou Women and Children's Medical Center). Licence **CC BY 4.0 VERIFIED** on the official record. One file, `ZhangLabData.zip`, 8,441,154,111 bytes, containing both eye scans and chest X-rays. The record does not state ages, demographics, image selection or ethics approval; "children aged 1 to 5, pneumonia versus normal" comes from secondary sources only. Needs the original *Cell* 2018 paper read and a supervisor decision.

**Unresolved approvals (all must be settled before any chest X-ray download):** read the official NIH terms yourself; supervisor approval of the dataset; whether "unrestricted with attribution" is enough for commercialisation; whether a public de-identified dataset needs its own ethics application; how to handle the pediatric gap; numeric targets.

