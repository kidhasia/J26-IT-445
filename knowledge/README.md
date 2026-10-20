# Reference corpus for the retrieval demo

`manifest.json` lists the documents the extractive retrieval demo (`POST /api/v1/rag-demo`) may search. Today it lists only **LUMI's own project documents** (model card, panel-defence record, OCR evaluation, evidence package). They are the project's write-ups. **They are not an approved medical knowledge base and must never be presented as medical advice.**

## Manifest fields (every one is checked when the server starts)
| Field | Meaning |
|---|---|
| `doc_id` | Short unique id: lower-case letters, digits, hyphens |
| `title` | Shown in citations |
| `path` | A `.md` file inside the project folder, written relative to this manifest (for example `../docs/MODEL_CARD_skin_pad_ufes20.md`). Paths that leave the project folder are rejected |
| `source_type` | `project_document`, or `approved_reference` (which **also requires** an `approved_by` record) |
| `licence` | Licence or ownership of the document, for example `project-owned` |
| `approved_for_medical_use` | `true` or `false`. Currently all `false` |

If any entry is missing, malformed, unsafe or unreadable, the whole demo reports `unavailable` (503) and nothing else in LUMI is affected.

## Adding a real medical source later (not part of phase 1)
Only after your supervisor approves the source **and** you have read and recorded its licence on the official page (see `docs/DATA_GOVERNANCE.md`): add the file, set `source_type` to `approved_reference`, fill `approved_by`, and set the population information once the loader supports it. Do not add documents you have not read and approved.

## Refreshing
The index is built when the server starts. After editing a listed document, restart the server. Each citation carries the first 12 characters of the file's SHA-256, so you can tell which version was searched.
