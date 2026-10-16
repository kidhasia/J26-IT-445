# data/

Everything in this folder except this README is ignored by Git (see `docs/DATA_GOVERNANCE.md` §4).

| Folder | Contents |
|---|---|
| `raw/` | Downloaded public datasets, exactly as downloaded (only after licence check and supervisor approval) |
| `processed/` | Preprocessed copies and split files |
| `synthetic/` | Generated synthetic reports (`scripts/make_synthetic_lab_reports.py`) |

Never put real patient data here unless ethics approval and a data-sharing agreement explicitly allow storage on this machine.
