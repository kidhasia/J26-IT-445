# Data Card: LUMI synthetic lab reports (v0.1)

Worked example of [the template](../templates/DATA_CARD_TEMPLATE.md), filled in for the only dataset LUMI uses so far.

## 1. Identity
| Field | Value |
|---|---|
| Dataset name and exact version | LUMI synthetic lab reports, generator v0.1 (git commit of `lumi/eval/synthetic_lab_reports.py`) |
| Official source | Generated locally by `lumi/eval/synthetic_lab_reports.py` |
| Date created | 2026-10-16 |
| Created by | Project code (IT23153318) |
| Storage path | `data/synthetic/lab_reports/` (git-ignored; regenerate with `scripts/make_synthetic_lab_reports.py`) |

## 2. Licence and permissions
Created by the project, with no third-party content. Uses Pillow's built-in default font; confirm its licence if images are published.

## 3. Approvals
No real person is described, so no ethics approval is needed for this data. Supervisor sign-off on its use as OCR test data: **pending**.

## 4. Content
| Field | Value |
|---|---|
| Modality | Computer-drawn report images (PNG/JPEG), one table layout |
| Records | 3 sample files from the script; tests generate more in memory |
| Label structure | Ground-truth JSON per image: test name, value, unit, reference range for each row |
| How labels were produced | They are the exact strings drawn, so ground truth is exact |

## 5. Population and bias
No patients. Values and reference ranges are **placeholders for software testing, not clinical reference values**. The images are much cleaner than real reports: one font, no skew, no photo blur, no stamps or handwriting, no logos or tables with borders. OCR results on this data **overestimate** real-world accuracy.

## 6. Privacy and identity risk
None: every image carries the banner "SYNTHETIC TEST REPORT - NOT REAL PATIENT DATA" and uses report IDs like `SYN-0001`.

## 7. Use in LUMI
| Field | Value |
|---|---|
| Intended task | FR4 / SO3: OCR and field-parsing tests; later, CER/WER measurement |
| Not intended for | Any clinical claim; training models that will be used on real patients |

## 8. Limitations to state in the thesis
- Single, clean, computer-generated layout; not representative of real laboratory reports.
- English only.

## 9. Change log
| Date | Change | By |
|---|---|---|
| 2026-10-16 | v0.1 created | IT23153318 |
