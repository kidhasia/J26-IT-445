# Data Card: <dataset name and version>

Copy this file to `docs/data_cards/<dataset>.md` and fill in every field **before** using the data.
Write "unknown" rather than guessing. Leave patient-level rows out of this file.

## 1. Identity
| Field | Value |
|---|---|
| Dataset name and exact version / edition | |
| Official source URL (not a mirror) | |
| DOI / paper | |
| Date accessed | |
| Downloaded by | |
| File checksums (SHA-256) or manifest location | |
| Local storage path (must be under `data/`, never committed) | |

## 2. Licence and permissions
| Field | Value |
|---|---|
| Licence name and version (exact text) | |
| URL where the licence was read, and date | |
| Commercial use allowed? | yes / no / unclear |
| Redistribution of data allowed? | yes / no / unclear |
| Sharing of trained model weights allowed? | yes / no / unclear |
| Registration / data use agreement / training required? Completed by whom, when? | |
| Required citation text | |
| Required acknowledgement text | |

## 3. Approvals
| Field | Value |
|---|---|
| Supervisor approval to use (name, date, how recorded) | |
| Ethics approval needed? Reference number, if any | |
| Consent basis (public release / informed consent / guardian consent) | |
| Data-sharing agreement reference (clinical data only) | |

## 4. Content
| Field | Value |
|---|---|
| Modality (dermatoscopic / clinical photo / chest X-ray / report image / Q&A text) | |
| Number of images / records / patients | |
| File formats and resolution | |
| Label structure (classes, multi-label?, answer types) | |
| How labels were produced (biopsy, expert, NLP-mined, generated) | |
| Label quality / known noise | |
| Metadata fields available | |

## 5. Population and bias
| Field | Value |
|---|---|
| Collection sites / countries / years | |
| Age distribution (how many children, i.e. under 18?) | |
| Sex distribution | |
| Skin tone / ethnicity information (if any) | |
| Class balance | |
| Known shortcuts or artefacts (rulers, markers, devices, burned-in text) | |
| Gap between this data and LUMI's real inputs (e.g. dermatoscopic vs phone photos) | |

## 6. Privacy and identity risk
| Field | Value |
|---|---|
| Direct identifiers present? (names, IDs, dates) | |
| Indirect identifiers (age + rare condition + site, burned-in text, EXIF) | |
| De-identification done by whom, using what method | |
| Patient/lesion grouping key used for splitting | |

## 7. Use in LUMI
| Field | Value |
|---|---|
| Intended task (requirement IDs, e.g. FR3, FR4) | |
| Uses that are NOT allowed / not intended | |
| Split method (by patient / lesion / official lists) | |
| Split files and their checksums | |
| Date splits were frozen (before any model comparison) | |
| Preprocessing applied | |

## 8. Limitations to state in the thesis
- 
- 

## 9. Change log
| Date | Change | By |
|---|---|---|
| | | |
