# Lab-report OCR evaluation (synthetic reports only)

Run on 2026-10-18 on the code that follows commit `aff7bc5` (the commit containing this file). Machine: Apple M5 Mac, Python 3.12.15, Pillow 12.3.0, Tesseract 5.5.3. All numbers below are copied from `docs/evaluations/ocr_synthetic_results.json`, which the command in §8 regenerates.

**One-paragraph summary.** On the three synthetic lab reports we have, the LUMI pipeline read the text with a **character error rate of 1.26%** and a **word error rate of 11.67%**, and plain Tesseract with **1.10% and 10.00%**. Every error in both systems was a **dropped space** next to a hyphen or a "<" sign (for example `75 - 95` read as `75-95`). No letter or digit was misread, no word or number was missing or invented, and nothing was read in the wrong order. The two systems differ by **one space in 637 characters**, which is too small to call either one better. **These results show only that the OCR works on clean, computer-drawn text. They say nothing about real clinical documents.**

---

## 1. What was evaluated

| | System | Exactly what runs |
|---|---|---|
| A | **LUMI pipeline** | `lumi.pipelines.ocr.pipeline.LabReportOcrPipeline`, the code the API runs. (1) **Preprocessing:** the image is turned upright using its EXIF tag and converted to greyscale. Nothing else: no sharpening, straightening, noise removal or resizing. (2) **Text extraction:** Tesseract 5.5.3, English, page-segmentation mode 6 ("one uniform block of text"). (3) **Line building:** Tesseract's words are grouped into lines in the order it reports them. (4) **Table parsing:** pattern matching turns lines into test / value / unit / reference-range fields. (5) **Normalisation:** values and units are copied as printed; the **only** change is that spacing inside a reference range is tidied (`75-95` becomes `75 - 95`, `<5` becomes `< 5`) |
| B | **Plain Tesseract** | `tesseract IMAGE stdout`: default settings (English, default page-segmentation mode 3) on the original image file. No preprocessing, no parsing |

Both are Tesseract underneath, so this is **not** a comparison of different OCR engines. It measures only what LUMI's preprocessing, page mode and line building add. The plain system is the "standard OCR engine with default configuration" baseline named in the proposal (Table 5).

## 2. Is the reference text genuinely correct?

The stored ground-truth files list only the **table rows**. The images also print a banner, a "Report ID" line and the column headings, so scoring against the rows alone would count those as errors. The reference therefore is the **complete printed text**, one string per printed line (columns left to right joined by one space; a blank cell is simply not printed). Evidence that it matches each image:

| Check | Result |
|---|---|
| I read all three images myself and compared them with their ground-truth files | The rows, the blank haemoglobin value in report 2 and the blank sodium range in report 3 all match |
| **Regeneration:** drawing each report again from its stored ground truth | **Byte-for-byte identical** to the stored image for all three, so the image was drawn from exactly those values |
| **Independent ink check** (uses no OCR and no drawing code): count the printed lines in the image, and for every table line check that columns with text contain ink and blank columns contain none | Passed for all three |
| The check can fail: five deliberate tamperings (wrong value, wrong report id, extra row, blank cell claimed but printed, value erased from the picture) | All caught; also covered by automated tests |
| The generator was changed so the drawing and the reference come from one list. Did that change any image? | **No.** The new code, the original code and the stored files give identical bytes (also an automated test that keeps a copy of the original drawing code as an oracle) |
| The original files were not edited | Their modification times are still 16 Oct 17:40:47 |

The evaluation program refuses to score a report whose reference fails these checks. The reference is never edited to improve a score.

Limit of this evidence: the independent ink check confirms which cells contain ink, not which characters they contain. The characters are confirmed by regeneration and by my own reading of the images.

## 3. How errors are counted

- **Edit distance:** the smallest number of **substitutions** (a reference item replaced by a different one), **deletions** (a reference item missing) and **insertions** (an extra item) that turns the reference into the system's text. Matches cost nothing.
- **CER** = character edit distance / number of reference characters. **WER** = word edit distance / number of reference words. Words are what is left after splitting on white space. A rate can exceed 100% if there are many insertions, and is undefined if the reference is empty but the output is not.
- The **total** edit distance is unique, but the split into S, D and I can tie (for example `ab` to `ba` is two substitutions, or one deletion plus one insertion). The program fixes one rule, the same for every system and report: prefer match or substitution, then deletion, then insertion.
- **Aggregates:** *micro* = total errors over total reference length across all reports (the headline); *macro* = the plain average of the per-report rates.

**Text changes before comparison.** Only white space is normalised; case, punctuation, digits, letters and word order are never touched, and no difficult text or wrong value is removed.

| Level | What is done | Used for |
|---|---|---|
| `cer_whitespace_normalised` (**primary**) | Every run of white space (spaces, new lines, form feeds) becomes one space; the ends are trimmed | CER headline |
| `cer_line_aware` | Spaces inside each line collapsed, blank lines dropped, line breaks kept as one character each | CER, checks line structure |
| `cer_raw` | No change at all, so blank lines and a trailing form feed count as characters | CER, shows formatting noise |
| `wer` | Splitting into words already ignores white space | WER |

## 4. The data

| | |
|---|---|
| Reports evaluated | **3** (`syn_0001_complete`, `syn_0002_missing_value`, `syn_0003_missing_range`) |
| Printed lines | 21 (9 + 6 + 6) |
| Reference size | **637 characters**, **120 words** (white-space normalised) |
| Table rows | 12, of which only **8 are distinct** (reports 2 and 3 reuse rows from report 1) |
| Nature | Computer-drawn: one layout, one font (Pillow's built-in default at 28 px), black on white, no noise, skew, blur, stamps, logos or handwriting. Every image says "SYNTHETIC TEST REPORT - NOT REAL PATIENT DATA". No real data of any kind was used |

## 5. Results

### Per report (CER primary level; S/D/I = substitutions / deletions / insertions)
| Report | Reference | LUMI CER | LUMI WER | Plain CER | Plain WER |
|---|---|---|---|---|---|
| syn_0001_complete | 277 chars, 54 words | 1.44% (0/4/0) | 12.96% (3/4/0) | 1.44% (0/4/0) | 12.96% (3/4/0) |
| syn_0002_missing_value | 185 chars, 35 words | 1.08% (0/2/0) | 8.57% (1/2/0) | 1.08% (0/2/0) | 8.57% (1/2/0) |
| syn_0003_missing_range | 175 chars, 31 words | 1.14% (0/2/0) | 12.90% (2/2/0) | 0.57% (0/1/0) | 6.45% (1/1/0) |

### Comparison (all three reports together)
| Measure | LUMI pipeline | Plain Tesseract |
|---|---|---|
| **CER, primary (micro)** | **1.26%** (8 errors in 637 characters: 0 S, 8 D, 0 I) | **1.10%** (7 in 637: 0 S, 7 D, 0 I) |
| CER, macro average of the 3 reports | 1.22% | 1.03% |
| **WER (micro)** | **11.67%** (14 errors in 120 words: 6 S, 8 D, 0 I) | **10.00%** (12 in 120: 5 S, 7 D, 0 I) |
| WER, macro average | 11.48% | 9.33% |
| CER, line-aware | 1.26% | 1.10% |
| CER, raw | 1.26% | 3.30% (21 edits: 4 S, 5 D, **12 I**) |
| Printed lines reproduced exactly | 15 of 21 | 16 of 21 |

Plain Tesseract's raw CER is higher only because its output contains blank lines between text blocks and a trailing form feed, which the raw level counts as inserted characters. The LUMI pipeline's output has no such padding.

### What kinds of errors occurred
| Kind of error | LUMI | Plain |
|---|---|---|
| Missing word or number | 0 | 0 |
| Extra word or number | 0 | 0 |
| Wrong characters inside a word (for example `l` for `1`) | 0 | 0 |
| Wrong number | 0 | 0 |
| Reading-order errors | 0 | 0 |
| **Word-boundary errors** (the same text with a space moved) | **14 word edits** | **12 word edits** |
| Character level: deleted spaces / any other kind | 8 / 0 | 7 / 0 |

Representative examples, all from the data: `75 - 95` read as `75-95` (both systems, 3 word edits each because three reference words become one), `3.9 - 5.8` read as `3.9 -5.8` (LUMI on reports 1 and 3, plain on report 1), `< 5` read as `<5` (both), `34 - 45` read as `34-45` (plain, report 2).

**Why WER looks so much worse than CER.** The reference prints `11.5 - 15.5` with spaces, so the hyphen is its own word. When a system drops one space, two correct words are scored as wrong. About 1 character in 100 is wrong, but about 1 word in 9 is. No information is lost: every digit and letter was read correctly.

### Field-level results (the parsed result rows)
This asks whether the pipeline's table parser returned the right test, value, unit and range for each of the 12 ground-truth rows (a blank cell is expected as "not found"). The plain system has no parser, so its lines were fed through the **same LUMI parser** for a secondary comparison.

| | LUMI pipeline | Plain Tesseract + LUMI parser |
|---|---|---|
| Rows found / parsed | 12 of 12 / 12 | 12 of 12 / 12 |
| Value, unit and range exactly right | 36 of 36 fields (100%) | 36 of 36 (100%) |
| Ranges that were right **only because of the parser's spacing tidy-up** | **6 of 12** | 5 of 12 |
| Rows with a wrong field that were not flagged for review ("silent errors") | 0 | 0 |
| Rows flagged for review | 2 (exactly the two rows where the report itself has a blank cell, so this is intended) | 12 (every row, because plain Tesseract gives no confidence scores, so the parser cannot tell) |

**Important:** the 100% field accuracy is partly produced by the tidy-up that turns `75-95` into `75 - 95`. That is a deliberate post-processing step, not better reading. It could not repair a misread digit. Also, the parser was written while looking at these same synthetic layouts, so this table is **not an independent test** of the parser.

## 6. What can and cannot be concluded

**Supported by the data**
- On clean, computer-drawn text in one layout, Tesseract (with or without LUMI's preprocessing) reads letters and digits correctly. The only mistakes seen are dropped spaces around `-` and `<`.
- The pipeline's reference-range tidy-up restores the printed spacing in every case where it was needed (6 of 6), and no wrong value reached the output unflagged.
- Both evaluations used exactly the same reference text for each report (the program records the same reference checksum for both systems).

**Not supported**
- **That LUMI's preprocessing, page mode or line building is better or worse than plain Tesseract.** The difference is one space in one report (`3.9 - 5.8`) among 637 characters. With three nearly identical reports, any ranking would be noise.
- **Any statement about real lab reports.** See §7.
- A confidence interval or significance test: with 3 reports and 8 distinct rows, none would be meaningful, so none is given.

## 7. Limitations

1. **Synthetic and clean.** One font, one layout, no noise, skew, blur, shadows, phone-camera distortion, stamps, logos, table borders, handwriting, low resolution, other languages, or multi-page documents. Real reports are all of these. **Performance on real clinical documents is unknown and should be expected to be worse.**
2. **Very small.** 3 reports, 637 characters, 12 table rows (8 distinct). Reports 2 and 3 reuse rows from report 1, so they are not independent samples.
3. **The reference comes from the same program that draws the image.** I verified it against the image (§2), but this still tests only how well rendered text is transcribed.
4. **Both systems are Tesseract.** Other engines (for example a cloud service or a document-AI model) were not tried, and sending reports to external services is not allowed for this project.
5. **CER and WER measure text fidelity, not medical correctness.** A misread digit in a value would be far more harmful than a dropped space, and a metric that counts them equally can hide that. The field-level table is closer to what matters, but it is in-sample (§5).
6. **Results depend on the Tesseract version, Pillow version and machine.** The versions are stored in the results file.
7. PDF reports are not supported by the pipeline and were not evaluated.
8. No numeric accuracy target exists yet (scope review C9), so no result here can be called a pass or a fail.

## 8. How to reproduce

```bash
cd "/Users/kidhasia/Desktop/Research Stuff"
.venv/bin/python scripts/make_synthetic_lab_reports.py     # only if data/synthetic/lab_reports is missing; recreates the same 3 files
.venv/bin/python -m lumi.eval.ocr_eval                      # verifies the references, scores both systems, writes docs/evaluations/ocr_synthetic_results.json
shasum -a 256 docs/evaluations/ocr_synthetic_results.json   # a second run gives the same checksum (68a8dfcc... with Tesseract 5.5.3 and Pillow 12.3.0)
.venv/bin/python -m pytest tests/test_text_metrics.py tests/test_ocr_eval.py -rs
```
The program stops with a clear message if a report is missing, malformed, not marked synthetic, or if its reference does not match its image (exit code 2); it never scores an unverified report. `--no-write` prints without writing a file.

## 9. Tests protecting the evaluation
`tests/test_text_metrics.py` (22 tests): edit distance against an independent implementation on 400 random pairs, hand-worked examples (kitten/sitting and others), the fixed tie-break rule, both-empty, nothing-recognised, empty-reference, rates above 100%, Unicode, case sensitivity, white-space handling, error categories (which always add up to the word edit distance), reading-order separation, character profile and line matching.
`tests/test_ocr_eval.py` (34 tests): the refactored generator draws identical images, the reference is what is printed, real reports pass verification, fourteen tampering and bad-input cases are caught (wrong value, wrong report id, extra row, missing row, a blank cell claimed but printed, a value erased from the picture, five kinds of unusable ground-truth file, and missing image, folder or reports), perfect / reads-nothing / one-character-wrong systems give the known scores, micro versus macro averaging is checked by hand, both systems get the same reference, text from the wrong report is scored as wrong, field scoring (wrong, missing, silent and invented rows), and the real Tesseract run including byte-identical repeat runs and refusing to score a tampered report.
I also broke the code on purpose three ways (micro averaging, the ink check, the reference text) and confirmed that the tests fail each time.
