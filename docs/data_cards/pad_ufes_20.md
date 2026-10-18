# Data Card: PAD-UFES-20 (v1)

Filled from [the template](../templates/DATA_CARD_TEMPLATE.md). Facts marked (verified) were read on the official sources on 2026-10-18 or measured on the downloaded files with `lumi.data_inspect`.

## 1. Identity
| Field | Value |
|---|---|
| Name / version | PAD-UFES-20, version 1 (published 2020-07-07) |
| Official source | Mendeley Data, doi:10.17632/zr7vgbcyr2.1 (verified) |
| Paper | Pacheco et al., *Data in Brief* 32:106221 (2020), doi:10.1016/j.dib.2020.106221 (verified) |
| Date accessed / downloaded by | 2026-10-18, by the project (student IT23153318 with an AI assistant) |
| Checksums | See `docs/DATA_GOVERNANCE.md` §5.2 |
| Local storage | `data/raw/PAD-UFES-20/` (never committed) |

## 2. Licence and permissions
| Field | Value |
|---|---|
| Licence | Creative Commons Attribution 4.0 International (verified on the record) |
| Commercial use | Allowed by the licence, with attribution. (The ImageNet-pretrained starting weights are a separate, unresolved question; see governance §5.3) |
| Redistribution | Allowed with attribution. This project nevertheless does not redistribute the data |
| Registration / agreement | None |
| Citation | Pacheco et al. 2020 (above) plus the dataset DOI |

## 3. Approvals
| Field | Value |
|---|---|
| Supervisor approval | **Pending** |
| Ethics | Stated by the authors: UFES ethics committee and Plataforma Brasil approval, patient consent (not independently checked). Whether this project needs its own approval for public data: **pending** |

## 4. Content
| Field | Value |
|---|---|
| Modality | Smartphone clinical photographs, PNG |
| Size | 2,298 images, 1,641 lesions, 1,373 patients |
| Labels | `diagnostic`: ACK 730, BCC 845, MEL 52, NEV 244, SCC 192, SEK 235 (verified; matches the paper's Table 2) |
| Label source | About 58% biopsy-proven, the rest clinical diagnosis (from the record). Per-class biopsy rates in the paper: BCC, MEL, SCC 100%; ACK 24%; NEV 25%; SEK 6% |
| Metadata | 26 columns, comma-separated: `patient_id, lesion_id, smoke, drink, background_father, background_mother, age, pesticide, gender, skin_cancer_history, cancer_history, has_piped_water, has_sewage_system, fitspatrick, region, diameter_1, diameter_2, diagnostic, itch, grew, hurt, changed, bleed, elevation, img_id, biopsed` (the paper spells Fitzpatrick "fitspatrick") |
| Image sizes | 147 to 3,476 px per side; 2,289 of 2,298 within 5% of square; 1,440 RGBA (all opaque) and 858 RGB |

## 5. Population and bias
| Field | Value |
|---|---|
| Source | One free dermatology program at the Federal University of Espirito Santo, Brazil, serving mainly low-income patients |
| Age | 6 to 94, median 62, mean 60.5. **39 images (23 patients) under 18, all NEV.** 12 images under 12 |
| Class balance | Very imbalanced: BCC 37%, ACK 32%, MEL 2.3% |
| Missing data | About 35% empty in many clinical-history columns (not used) |
| Known quality issues found by us | 15 exact duplicate files, all within one patient; in 12 of 15 pairs the two records carry different diagnosis labels |
| Gap to LUMI's real inputs | Photos come from the program's own collection app and devices; other phones, lighting and parents' photos of children are not represented |

## 6. Privacy and identity risk
Authors state consent and privacy preservation. The data contains `patient_id` and pseudonymous file names (not directly identifying). Use `patient_id` only for splitting. Do not link records to real people, and never print id lists. Close-up body photos can show identifying features such as faces or tattoos; this project does not inspect individual images for that.

## 7. Use in LUMI
| Field | Value |
|---|---|
| Task | FR3/SO2: six-class skin-lesion classifier (research prototype) |
| Not for | Clinical use; any claim about children; any claim about lesions outside the six classes |
| Split method | Patient-level, stratified by diagnosis, 5-fold grouping (train / validation / test), seed 42 |
| Duplicate handling | Drop all copies of an image whose copies disagree on the label (24 images); keep one copy when they agree (3 dropped); 2,271 images used |
| Preprocessing | Upright (EXIF), RGB, longest side resized to 256 px, padded to a square (nothing cropped), ImageNet normalisation |

## 8. Limitations to state in the thesis
- Essentially adult data: only 39 of 2,298 images are from under-18s, all benign nevus.
- Six classes only; every image is forced into one of them.
- A small test split, with few melanoma cases, gives wide uncertainty on per-class results.
- One source programme in Brazil; skin-tone coverage can be checked through the `fitspatrick` column but has not been analysed.

## 9. Change log
| Date | Change | By |
|---|---|---|
| 2026-10-18 | Downloaded, verified, inspected; card created | IT23153318 |
