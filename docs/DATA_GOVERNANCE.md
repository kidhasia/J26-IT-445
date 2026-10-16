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
| Licence / terms to review | Commonly reported as **CC BY-NC 4.0** (non-commercial). **Verify on the Dataverse page.** If non-commercial is confirmed, models trained on it may not be usable commercially; this matters for PROP §6. |
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
