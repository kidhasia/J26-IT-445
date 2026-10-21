# Panel defence record: LUMI skin-lesion classifier

**LUMI is a research prototype. It is not clinically validated and must not be used for diagnosis.** Run `20261018T072750Z`, written 2026-10-20. Full details: `docs/MODEL_CARD_skin_pad_ufes20.md`.

**How to read this page.** *Verified (audit)* means I re-checked it myself on 2026-10-19/20 by running code against the real files. *Project record* means it comes from the run's own files or earlier documents and I did not re-derive it. *Ad hoc* means my audit check was a throw-away script that is **not saved in the repository**.

## A. Model and training
| Item | Detail (source) |
|---|---|
| Task | One skin photo scored against six classes: ACK, BCC, MEL, NEV, SCC, SEK (`classes.json`) |
| Model | EfficientNet-B0 (timm 1.0.30); ImageNet-pretrained start, `timm/efficientnet_b0.ra_in1k`; classifier head replaced (1000 to 6 outputs); **all layers trained** (`config.json`, `lumi/ml/train_skin.py`) |
| Data | PAD-UFES-20 v1, smartphone photos, CC BY 4.0. 2,298 files; after the duplicate rule 2,271 used (`config.json`) |
| Preprocessing | Upright by EXIF, RGB, longest side resized to 256 px and padded to a square (not cropped), ImageNet mean/std normalisation (`lumi/ml/skin_model.py`) |
| Augmentation (training only) | Horizontal and vertical flip, rotation up to 20 degrees, random resized crop (scale 0.75 to 1.0), small colour jitter (`train_skin.py`) |
| Loss and balance | Cross-entropy with class weights from the inverse square root of class frequency: MEL 2.75, NEV 1.25, SCC 1.43, SEK 1.27, ACK 0.72, BCC 0.67 (`config.json`) |
| Optimiser and schedule | AdamW, learning rate 3e-4, weight decay 1e-4, cosine decay over 12 epochs, batch 32, seed 42, Apple GPU (MPS), 402 seconds |
| Split | Patient-level, stratified, 5-fold: train 1,362 images / 823 patients, validation 454 / 273, test 455 / 275 |
| Selection | Best epoch chosen on **validation** macro-F1; test split evaluated **once** afterwards (`train_skin.py` header and code) |

**Training history** (`training_log.csv`, project record; consistent with the code). Training loss fell from 2.24 to 0.13. Validation macro-F1 rose from 0.379 to its peak of **0.549 at epoch 7**, then stayed between 0.536 and 0.547; validation accuracy ended at 0.654. Epoch 7 was kept. My reading (an interpretation, not a measured fact): training loss kept falling while validation stopped improving, so later epochs mostly fit the training photos.

## B. Evaluation on the held-out test split (455 images)
| Metric | Result | Status |
|---|---|---|
| Accuracy | **63.30%** | Verified (audit): recomputed with scikit-learn from the checkpoint's own predictions; equals `metrics.json` |
| Macro-F1 | **0.5428** | Verified (audit) |
| Balanced accuracy | **55.21%** | Verified (audit) |
| Macro ROC-AUC (one-vs-rest) | **0.8596** | Verified (audit) |
| Accuracy, 95% bootstrap interval | **58.4% to 68.1%** | Verified (audit): `scripts/bootstrap_test_ci.py`, 2,000 patient-level resamples |
| Macro-F1, 95% bootstrap interval | **0.461 to 0.609** | Verified (audit), same script |

**Baseline.** A model that always answers the commonest class (BCC) scores **36.5% accuracy and 0.089 macro-F1**. LUMI is clearly better than that, but is still wrong for about 1 photo in 3. The wide macro-F1 interval shows that the test set is small.

## C. Reproducibility and implementation
- **Checkpoint:** `models/skin_pad_ufes20/20261018T072750Z/checkpoint.pt` (16,338,553 bytes; Git-ignored, so it is not on GitHub).
- **SHA-256 (full, computed from the file on 2026-10-20):** `ec4f8afd39e04fac1244f194f2070f66efbca109b26f1a654ddf23ba58316dd0` (check with `shasum -a 256 <path>`). This hash was not recorded anywhere earlier.
- **Commands I ran** (each is a script in the repository; its usage line is in the script). Run from the project folder; `R=models/skin_pad_ufes20/20261018T072750Z`, `M=data/raw/PAD-UFES-20/metadata.csv`, `I=data/raw/PAD-UFES-20/images`:
```
.venv/bin/python scripts/check_api_matches_training.py $R $M $I
.venv/bin/python scripts/bootstrap_test_ci.py $R $M $I
```
The retraining command is in model card section 8 (`python -m lumi.ml.train_skin --metadata ... --images ... --out-dir ...`); I did not run it.
- **Serving matches evaluation (Verified, audit):** the real API code gave the same predicted class as the offline evaluation for **454 of 455** test images. The one remaining image was rejected by the 10 MB upload limit (`413 file_too_large`). The largest probability difference among served images was 0.0001 (the API rounds to four decimals). Macro-F1 on the 454 served images was 0.5425.
- **Fine-tuned from pretrained weights (evidence, not proof of origin):**
  - `config.json` says `pretrained: true`, and the checkpoint stores `pretrained_backbone: True` (project record).
  - *Ad hoc audit check:* compared with the locally cached `timm/efficientnet_b0.ra_in1k`, the checkpoint's backbone is **close** (relative distance 0.24) but **changed** (0 of 358 backbone tensors identical). A random initialisation would be about 14.8 away from the checkpoint. So the backbone started from ImageNet-like weights and was altered by training.
  - Not saved: the full training console output, and which pretrained file was downloaded at training time (the cached copy is consistent with it but does not prove it).
- **Evaluating the existing checkpoint is reproducible** (same checkpoint, same data, same scripts give the same numbers). **Retraining is not guaranteed to give identical weights or results:** GPU (MPS) training is not bit-for-bit repeatable even with a fixed seed (`config.json` notes).

## D. Dataset integrity
- **Patients (Verified, audit; ad hoc check plus the project's own `verify_no_patient_leakage`, which runs in training):** no patient appears in more than one of train, validation and test.
- **Lesions (Verified, audit; ad hoc):** no (patient, lesion) pair is shared across splits. `lesion_id` numbers are reused between patients (246 ids), so lesions were compared together with the patient id. Because whole patients are kept together, lesion-level separation follows.
- **Exact duplicates (Verified, audit; ad hoc):** 0 identical files sit in different splits. The project's duplicate rule (project record) removed 27 files first; 24 of them were pairs with conflicting labels.
- **Not checked:** near-duplicate or very similar photos of different patients. Only exact identical files were compared.
- Grouping matters: 538 of 1,371 patients have several photos (up to 10), so a photo-level split would have leaked.

## E. Limitations (say these before the panel asks)
- **Melanoma:** the test set has only **11** melanomas. The model found **4 (recall 36.4%, 95% interval 0.0% to 77.8%)** and labelled 4 as nevus, a benign class. 6 non-melanoma photos were labelled melanoma. The real melanoma performance is essentially unknown. The weighted loss did not fix this.
- **Children:** only **39 images** (23 patients) in the dataset are from patients under 18, and **all are labelled nevus**. The test split has 6 of them (all predicted correctly). That shows nothing about other conditions in children. **No pediatric validation exists.**
- **No clinical validation.** No clinician has reviewed the model, its predictions or its attention maps.
- **One training run, one split.** The model card interval reflects test-sample uncertainty only, not run-to-run variation.
- **Not available:** a from-scratch (random initialisation) comparison, calibration analysis (the score is a relative model score, not a probability of being correct), an external test set, and a skin-tone subgroup evaluation (Fitzpatrick type is mostly missing and was not analysed).
- Do **not** claim that pretraining improved performance (it was never compared), or that the system is suitable for diagnosis, triage or screening.

## F. Likely panel questions
1. **What did you train?** An EfficientNet-B0 image classifier that scores a skin photo against six classes, trained on 1,362 public PAD-UFES-20 photos. It is one component of the LUMI backend and gives a relative score, not a diagnosis.
2. **Was it trained from scratch?** No. It started from ImageNet-pretrained weights and all layers were then trained on the skin photos. I checked that the weights are close to the pretrained ones but changed. I have not compared it with a from-scratch model, so I cannot say how much the pretraining helped.
3. **How did you evaluate it?** On 455 photos from 275 patients that were never used for training or for choosing the epoch. I evaluated once, then added patient-level bootstrap intervals and a majority-class baseline.
4. **How did you avoid patient-level leakage?** Splitting is by patient, stratified by diagnosis, with a check that stops training if a patient appears in two splits. I also confirmed that no lesion or identical file crosses splits. I did not check near-duplicates between different patients.
5. **What do accuracy and macro-F1 tell us?** Accuracy (63%) is the share of correct photos; it is boosted by common classes. Macro-F1 (0.54) averages all six classes equally, so rare, hard classes such as melanoma pull it down. Both beat the always-BCC baseline (36.5% and 0.089) but are modest, and the intervals are wide.
6. **Why is melanoma recall a concern?** Missing a melanoma is the most serious error. Only 4 of 11 were found and 4 were called nevus. With 11 test cases the true rate could be anywhere from near zero to about 78%, so I cannot make any melanoma claim.
7. **Can you claim it is validated for children?** No. The data has 39 pediatric photos, all benign nevus, so it cannot show performance on other conditions in children. A pediatric claim would need pediatric data and ethics approval.
8. **What are the next improvements?** A from-scratch comparison on the same split; repeated runs for variability; calibration; a skin-tone analysis; an external dataset; more melanoma data; and review by a clinician. Chest X-ray and a trained question-answering model are separate, unfinished parts of LUMI.
