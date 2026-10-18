# Model Card: LUMI skin-lesion classifier, run 20261018T072750Z

**Research prototype. Not clinically validated. Not for diagnosis. Not shown to be reliable for children.**

All numbers below were produced on 2026-10-18 by the commands in §8 and are copied from `metrics.json` and the scripts' output. The checkpoint itself lives in `models/` (ignored by Git).

## 1. What it is
| | |
|---|---|
| Task | Score one photo against six lesion classes: ACK, BCC, MEL, NEV, SCC, SEK |
| Model | EfficientNet-B0 (timm 1.0.30), fine-tuned with transfer learning from `timm/efficientnet_b0.ra_in1k` (Apache-2.0 card; trained on ImageNet-1k) |
| Input handling | Upright by EXIF, RGB, longest side resized to 256 px, padded to a square (nothing cropped) |
| Output | Class probabilities. `confidence` = the top probability, **the model's relative score, not clinical certainty** |
| Training | 12 epochs, AdamW lr 3e-4, batch 32, tempered inverse-frequency class weights, flip/rotation/crop/colour augmentation, seed 42, Apple MPS GPU, 402 s |
| Epoch chosen | Epoch 7, selected on the **validation** split (validation macro-F1 0.549) |
| Code version | git commit `cee09208d9ba5d43a1766f9c3094efafbe0379fc`, no uncommitted changes at training time |

## 2. Data
PAD-UFES-20 v1 (CC BY 4.0, smartphone photos, Brazil). Full record: `docs/data_cards/pad_ufes_20.md` and `docs/DATA_GOVERNANCE.md` §5.
After removing duplicate images (rule in the data card), **2,271 images** were used. Split by **patient** (no patient appears in two splits; checked in code):

| Split | Images | Patients | ACK | BCC | MEL | NEV | SCC | SEK |
|---|---|---|---|---|---|---|---|---|
| Train | 1,362 | 823 | 434 | 501 | 30 | 146 | 111 | 140 |
| Validation | 454 | 273 | 144 | 167 | 11 | 48 | 37 | 47 |
| Test | 455 | 275 | 145 | 166 | 11 | 49 | 37 | 47 |

## 3. Results on the held-out TEST split (evaluated once, after all choices were final)
| Measure | Value | 95% interval (patient-level bootstrap, 2,000 resamples) |
|---|---|---|
| Accuracy | 0.633 | 0.584 to 0.681 |
| Macro-F1 | 0.543 | 0.461 to 0.609 |
| Balanced accuracy | 0.552 | not computed |
| Macro ROC-AUC (one-vs-rest) | 0.860 | not computed |
| *Baseline: always predict the commonest class (BCC)* | accuracy 0.365, macro-F1 0.089 | |

Validation (used to pick the epoch, so **not** an unbiased estimate): macro-F1 0.549, accuracy 0.632.

### Per class (test)
| Class | Precision | Recall | F1 | Test images | 95% interval for recall |
|---|---|---|---|---|---|
| ACK Actinic keratosis | 0.692 | 0.683 | 0.688 | 145 | 0.60 to 0.76 |
| BCC Basal cell carcinoma | 0.726 | 0.669 | 0.696 | 166 | 0.59 to 0.75 |
| MEL Melanoma | 0.400 | 0.364 | 0.381 | **11** | **0.00 to 0.78** |
| NEV Melanocytic nevus | 0.556 | 0.816 | 0.661 | 49 | 0.69 to 0.92 |
| SCC Squamous cell carcinoma | 0.250 | 0.270 | 0.260 | 37 | 0.10 to 0.44 |
| SEK Seborrheic keratosis | 0.649 | 0.511 | 0.571 | 47 | 0.35 to 0.67 |

### Confusion matrix (rows = true class, columns = predicted)
| | ACK | BCC | MEL | NEV | SCC | SEK |
|---|---|---|---|---|---|---|
| **ACK** | 99 | 21 | 2 | 5 | 13 | 5 |
| **BCC** | 30 | 111 | 1 | 6 | 16 | 2 |
| **MEL** | 2 | 0 | 4 | 4 | 0 | 1 |
| **NEV** | 2 | 1 | 1 | 40 | 1 | 4 |
| **SCC** | 9 | 16 | 0 | 1 | 10 | 1 |
| **SEK** | 1 | 4 | 2 | 16 | 0 | 24 |

Reading it: the model is clearly better than guessing, but it is wrong for roughly 1 photo in 3. It often mixes up ACK, BCC and SCC with each other, and calls 16 of 47 seborrheic keratoses "nevus". Of 11 melanomas it found 4 and called 4 "nevus" (a benign class), which is the most worrying kind of mistake. The test set is far too small to say how often that really happens.

## 4. Children: what the data can and cannot say
- Only **39 of 2,298** dataset images are from patients under 18, and **all are labelled benign nevus**. After duplicate removal: train 27 images (16 children), validation 6, **test 6 images from 3 children**.
- All 6 test images from children were classified correctly (and 34 of 43 adult nevus images). Six photos of one benign class from three patients **do not show the model is reliable for children**, and there is no data at all for pediatric BCC, SCC, melanoma, ACK or SEK.
- The test patients' ages: minimum 8, median 62, maximum 94. Adult test accuracy was 0.628.
- **Conclusion: this model must not be described as pediatric, nor as validated for children.** Pediatric evidence needs pediatric data collected with ethics approval (scope review C5, C11).

## 5. Verification that serving matches evaluation
`scripts/check_api_matches_training.py` sent all 455 test images through the real API code. 454 were served and gave **the identical predicted class** as the offline evaluation (largest probability difference 0.0001, from rounding); 1 image was refused with `413 file_too_large`. Across the whole dataset, 10 of 2,298 PNG files exceed the API's 10 MB upload limit; a client must compress very large photos before upload.

## 6. Limitations (also returned by the API in every skin response)
- Six classes only: any image, including non-skin or other conditions, is forced into one of them.
- One small public dataset from one Brazilian programme; other phones, lighting, skin tones, body sites and populations are untested. Skin-tone coverage (`fitspatrick` column) has not been analysed.
- Few melanoma images (11 in test), so melanoma results are essentially unknown; the same caution applies to every per-class figure.
- Labels: about 58% biopsy-proven, the rest clinical diagnosis; label noise is possible. 12 duplicate pairs had conflicting labels and were excluded.
- One training run and one split; no repeated runs, no hyperparameter search, no external test set.
- No explanation of which image regions drive a score (Grad-CAM not implemented).
- MPS training is not bit-for-bit reproducible even with a fixed seed.
- The ImageNet-pretrained starting weights have an unresolved licence question for commercial use (governance §5.3).
- The model has had no clinical review.

## 7. Intended and out-of-scope use
Intended: a software demonstration of a model-serving pipeline for a research project, with every output accompanied by the clinical-boundary notice.
Out of scope: diagnosis, triage, screening, any use with real patients, any claim about children.

## 8. How to reproduce
```bash
.venv/bin/python -m lumi.ml.train_skin --metadata data/raw/PAD-UFES-20/metadata.csv --images data/raw/PAD-UFES-20/images --out-dir models/skin_pad_ufes20
.venv/bin/python scripts/check_api_matches_training.py models/skin_pad_ufes20/<run id> data/raw/PAD-UFES-20/metadata.csv data/raw/PAD-UFES-20/images
.venv/bin/python scripts/bootstrap_test_ci.py models/skin_pad_ufes20/<run id> data/raw/PAD-UFES-20/metadata.csv data/raw/PAD-UFES-20/images
```
A new training run will give slightly different numbers (GPU non-determinism); the numbers above belong to run `20261018T072750Z`.
