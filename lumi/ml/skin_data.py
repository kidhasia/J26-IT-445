"""PAD-UFES-20 loading and patient-level splitting.

Column names (img_id, patient_id, lesion_id, diagnostic) were confirmed against the real
metadata.csv header and the dataset paper (Pacheco et al., Data in Brief 32:106221).
Splitting groups by patient_id so that no patient appears in more than one split.
Nothing here prints ids, file names or row values; only counts are reported.
"""

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

CLASSES = ("ACK", "BCC", "MEL", "NEV", "SCC", "SEK")
CLASS_NAMES = {
    "ACK": "Actinic keratosis",
    "BCC": "Basal cell carcinoma",
    "MEL": "Melanoma",
    "NEV": "Melanocytic nevus",
    "SCC": "Squamous cell carcinoma (includes Bowen's disease)",
    "SEK": "Seborrheic keratosis",
}
REQUIRED_COLUMNS = ("img_id", "patient_id", "lesion_id", "diagnostic")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")


class DataError(Exception):
    """The dataset is missing, inconsistent or not what the code expects."""


@dataclass(frozen=True)
class Sample:
    img_id: str
    patient_id: str
    lesion_id: str
    label: str
    path: Path


def find_images(images_root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in sorted(images_root.rglob("*")):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS and not path.name.startswith("."):
            if path.name in found:
                raise DataError("Two image files share the same file name; cannot match them to metadata unambiguously.")
            found[path.name] = path
    return found


def load_samples(metadata_path: Path, images_root: Path) -> list[Sample]:
    if not metadata_path.is_file():
        raise DataError("The metadata file does not exist.")
    if not images_root.is_dir():
        raise DataError("The image folder does not exist.")
    images = find_images(images_root)
    with metadata_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = [name.strip() for name in (reader.fieldnames or [])]
        missing = [name for name in REQUIRED_COLUMNS if name not in header]
        if missing:
            raise DataError(f"Metadata is missing required column(s) {missing}. Columns found: {header}.")
        rows = list(reader)

    samples: list[Sample] = []
    unknown_labels: Counter = Counter()
    rows_without_image = 0
    for row in rows:
        label = (row["diagnostic"] or "").strip()
        if label not in CLASSES:
            unknown_labels[label or "(empty)"] += 1
            continue
        path = images.get((row["img_id"] or "").strip())
        if path is None:
            rows_without_image += 1
            continue
        samples.append(Sample(row["img_id"].strip(), row["patient_id"].strip(), row["lesion_id"].strip(), label, path))
    if unknown_labels:
        raise DataError(f"{sum(unknown_labels.values())} row(s) have a diagnosis outside {list(CLASSES)}: {dict(unknown_labels)}.")
    if rows_without_image:
        raise DataError(f"{rows_without_image} metadata row(s) have no matching image file.")
    if not samples:
        raise DataError("No samples were found.")
    if any(not s.patient_id for s in samples):
        raise DataError("Some rows have no patient_id, so patient-level splitting is not possible.")
    return sorted(samples, key=lambda s: s.img_id)


def resolve_duplicates(samples: list[Sample]) -> tuple[list[Sample], dict]:
    """Handle images that are byte-for-byte identical files.

    Rule (fixed before any model was trained): if all copies carry the same label, keep one (the first by img_id);
    if the copies carry DIFFERENT labels, drop every copy, because the same pixels cannot be right for two labels.
    The source files are not touched; this only decides which samples are used.
    """
    import hashlib

    groups: dict[str, list[Sample]] = {}
    for sample in samples:
        digest = hashlib.sha256(sample.path.read_bytes()).hexdigest()
        groups.setdefault(digest, []).append(sample)
    dropped: set[str] = set()
    duplicate_groups = conflicting_groups = redundant = conflicting_images = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        duplicate_groups += 1
        ordered = sorted(group, key=lambda s: s.img_id)
        if len({s.label for s in ordered}) > 1:
            conflicting_groups += 1
            conflicting_images += len(ordered)
            dropped.update(s.img_id for s in ordered)
        else:
            redundant += len(ordered) - 1
            dropped.update(s.img_id for s in ordered[1:])
    kept = [s for s in samples if s.img_id not in dropped]
    report = {
        "rule": "identical files: keep one copy if labels agree; drop all copies if labels conflict",
        "duplicate_groups": duplicate_groups,
        "groups_with_conflicting_labels": conflicting_groups,
        "images_dropped_because_labels_conflict": conflicting_images,
        "images_dropped_as_redundant_copies": redundant,
        "images_before": len(samples),
        "images_after": len(kept),
    }
    return kept, report


def make_splits(
    samples: list[Sample], seed: int = 42, n_folds: int = 5, test_fold: int = 0, val_fold: int = 1
) -> dict[str, str]:
    """Return {img_id: 'train'|'val'|'test'}. Patient-level, stratified by diagnosis, reproducible for a seed."""
    from sklearn.model_selection import StratifiedGroupKFold

    if test_fold == val_fold or not (0 <= test_fold < n_folds and 0 <= val_fold < n_folds):
        raise DataError("test_fold and val_fold must be different folds in range.")
    splitter = StratifiedGroupKFold(n_splits=n_folds, shuffle=True, random_state=seed)
    folds = [held_out for _, held_out in splitter.split(range(len(samples)), [s.label for s in samples], [s.patient_id for s in samples])]
    assignment = {s.img_id: "train" for s in samples}
    for index in folds[val_fold]:
        assignment[samples[index].img_id] = "val"
    for index in folds[test_fold]:
        assignment[samples[index].img_id] = "test"
    verify_no_patient_leakage(samples, assignment)
    return assignment


def verify_no_patient_leakage(samples: list[Sample], assignment: dict[str, str]) -> None:
    patients_by_split: dict[str, set[str]] = {}
    for sample in samples:
        patients_by_split.setdefault(assignment[sample.img_id], set()).add(sample.patient_id)
    names = sorted(patients_by_split)
    for i, first in enumerate(names):
        for second in names[i + 1 :]:
            shared = patients_by_split[first] & patients_by_split[second]
            if shared:
                raise DataError(f"Patient leakage: {len(shared)} patient(s) appear in both '{first}' and '{second}'.")


def split_summary(samples: list[Sample], assignment: dict[str, str]) -> dict:
    """Aggregate counts per split: images, patients and class distribution."""
    summary: dict[str, dict] = {}
    for split in ("train", "val", "test"):
        chosen = [s for s in samples if assignment[s.img_id] == split]
        counts = Counter(s.label for s in chosen)
        summary[split] = {
            "images": len(chosen),
            "patients": len({s.patient_id for s in chosen}),
            "classes": {name: counts.get(name, 0) for name in CLASSES},
        }
    return summary
