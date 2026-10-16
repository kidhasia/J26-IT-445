"""Read-only dataset inspection: counts, labels, missing values, corrupt and duplicate files, image sizes.

Safety rules this module follows:
- Source data is only ever opened for reading; nothing is written next to it.
- The summary contains counts and aggregate statistics only. It never contains file names,
  ids, row values or paths. The only values it lists are the classes of the one column the
  user names as the label column, and only when that column looks like a real label column
  (few distinct, short values).
- Column names are never assumed: configured names are checked against the real header and
  any mismatch is reported (with near-miss suggestions) instead of guessed.
"""

import csv
import hashlib
import math
import re
import statistics
import warnings
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

TOOL_VERSION = 1
PLACEHOLDER_TOKENS = frozenset({"na", "n/a", "nan", "null", "none", "unknown", "?", "-"})
MAX_LABELS_SHOWN = 50
MAX_LABEL_LENGTH = 60
DISTINCT_CAP = 200_000
TOP_SIZES_SHOWN = 10
PROGRESS_EVERY = 500
HASH_CHUNK_BYTES = 1024 * 1024
DELIMITER_NAMES = {"\t": "tab", ",": "comma", ";": "semicolon"}
PRIVACY_NOTE = (
    "This summary contains counts and aggregate statistics only. It lists no file names, ids, paths or row values; "
    "the only values shown are the classes of the configured label column."
)


class InspectionError(Exception):
    """A problem that prevents inspection (missing folder, unreadable metadata file, bad option)."""


@dataclass(frozen=True)
class InspectionConfig:
    name: str
    image_dir: Path
    metadata_path: Path | None = None
    delimiter: str | None = None  # None = detect from the header line
    id_column: str | None = None
    label_column: str | None = None
    label_separator: str | None = None  # e.g. "|" when one cell holds several labels
    group_column: str | None = None  # e.g. patient or lesion id, used to warn about split leakage
    numeric_columns: tuple[str, ...] = ()
    image_extensions: tuple[str, ...] = (".jpg", ".jpeg", ".png")
    check_level: str = "full"  # "full" decodes every image; "header" only checks that the file opens
    config_source: str = "command line"


@dataclass
class InspectionResult:
    summary: dict  # safe to save and share
    problem_files: dict[str, list[str]]  # relative file paths; local use only, never put in the summary


def inspect_dataset(config: InspectionConfig, progress: Callable[[int, int], None] | None = None) -> InspectionResult:
    if config.check_level not in ("header", "full"):
        raise InspectionError("check_level must be 'header' or 'full'.")
    if not config.image_dir.is_dir():
        raise InspectionError("The image folder does not exist or is not a folder.")

    files_section, image_paths = _scan_files(config)
    images_section, problems = _inspect_images(config, image_paths, progress)

    metadata_section = None
    id_counter: Counter | None = None
    if config.metadata_path is not None:
        metadata_section, id_counter = _inspect_metadata(config)
    cross_check = _cross_check(config, image_paths, id_counter)

    summary = {
        "tool": {"name": "lumi-dataset-inspector", "version": TOOL_VERSION},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset_name": config.name,
        "privacy_note": PRIVACY_NOTE,
        "config": {
            "config_source": config.config_source,
            "image_folder_name": config.image_dir.resolve().name,
            "metadata_file_name": config.metadata_path.name if config.metadata_path else None,
            "delimiter": DELIMITER_NAMES.get(config.delimiter, config.delimiter) if config.delimiter else None,
            "id_column": config.id_column,
            "label_column": config.label_column,
            "label_separator": config.label_separator,
            "group_column": config.group_column,
            "numeric_columns": list(config.numeric_columns),
            "image_extensions": list(config.image_extensions),
            "check_level": config.check_level,
        },
        "files": files_section,
        "images": images_section,
        "metadata": metadata_section,
        "cross_check": cross_check,
        "warnings": [],
    }
    summary["warnings"] = _collect_warnings(summary)
    return InspectionResult(summary=summary, problem_files=problems)


# ---------------------------------------------------------------- files and images


def _scan_files(config: InspectionConfig) -> tuple[dict, list[Path]]:
    root = config.image_dir
    extensions = {ext.lower() for ext in config.image_extensions}
    all_files: list[Path] = []
    hidden_skipped = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            hidden_skipped += 1
            continue
        all_files.append(path)
    by_extension = Counter(path.suffix.lower() or "(none)" for path in all_files)
    image_paths = [path for path in all_files if path.suffix.lower() in extensions]
    section = {
        "total_files": len(all_files),
        "hidden_files_skipped": hidden_skipped,
        "image_files": len(image_paths),
        "non_image_files": len(all_files) - len(image_paths),
        "by_extension": dict(sorted(by_extension.items())),
    }
    return section, image_paths


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_image(path: Path, level: str) -> tuple[str, tuple[int, int, str, str | None] | None]:
    """Return (status, (width, height, mode, format)); status is ok / corrupt / too_large."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as img:
                info = (img.width, img.height, img.mode, img.format)
                if level == "full":
                    img.load()  # decodes every pixel; catches truncated files
                else:
                    img.verify()
        return "ok", info
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        return "too_large", None
    # Pillow raises many exception types for damaged files; any of them means "corrupt".
    except Exception:  # noqa: BLE001
        return "corrupt", None


def _numeric_summary(values: list[float]) -> dict | None:
    if not values:
        return None
    return {
        "min": min(values),
        "max": max(values),
        "mean": round(statistics.fmean(values), 3),
        "median": round(statistics.median(values), 3),
    }


def _inspect_images(
    config: InspectionConfig, image_paths: list[Path], progress: Callable[[int, int], None] | None
) -> tuple[dict, dict[str, list[str]]]:
    root = config.image_dir
    status_counts: Counter = Counter()
    formats: Counter = Counter()
    modes: Counter = Counter()
    sizes: Counter = Counter()
    widths: list[int] = []
    heights: list[int] = []
    by_hash: dict[str, list[str]] = {}
    problems: dict[str, list[str]] = {"corrupt": [], "too_large": [], "unreadable": [], "duplicates": []}

    for number, path in enumerate(image_paths, start=1):
        relative = path.relative_to(root).as_posix()
        try:
            by_hash.setdefault(_sha256(path), []).append(relative)
        except OSError:
            status_counts["unreadable"] += 1
            problems["unreadable"].append(relative)
            continue
        status, info = _check_image(path, config.check_level)
        status_counts[status] += 1
        if status == "ok" and info is not None:
            width, height, mode, image_format = info
            widths.append(width)
            heights.append(height)
            sizes[f"{width}x{height}"] += 1
            modes[mode] += 1
            formats[image_format or "unknown"] += 1
        else:
            problems[status].append(relative)
        if progress and number % PROGRESS_EVERY == 0:
            progress(number, len(image_paths))
    if progress and image_paths:
        progress(len(image_paths), len(image_paths))

    groups = [paths for paths in by_hash.values() if len(paths) > 1]
    for index, group in enumerate(groups, start=1):
        problems["duplicates"].extend(f"group {index}: {relative}" for relative in group)

    ok_count = status_counts["ok"]
    section = {
        "checked": len(image_paths),
        "ok": ok_count,
        "corrupt": status_counts["corrupt"],
        "too_large": status_counts["too_large"],
        "unreadable": status_counts["unreadable"],
        "check_level": config.check_level,
        "dimensions": None
        if not ok_count
        else {
            "width": _numeric_summary(widths),
            "height": _numeric_summary(heights),
            "distinct_sizes": len(sizes),
            "most_common_sizes": [{"size": s, "count": c} for s, c in sizes.most_common(TOP_SIZES_SHOWN)],
            "color_modes": dict(sorted(modes.items())),
            "formats": dict(sorted(formats.items())),
        },
        "duplicates": {
            "duplicate_groups": len(groups),
            "files_in_duplicate_groups": sum(len(group) for group in groups),
            "extra_copies": sum(len(group) - 1 for group in groups),
            "largest_group": max((len(group) for group in groups), default=0),
        },
    }
    return section, problems


# ---------------------------------------------------------------- metadata


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _detect_delimiter(header_line: str) -> str:
    counts = {delimiter: header_line.count(delimiter) for delimiter in DELIMITER_NAMES}
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def _inspect_metadata(config: InspectionConfig) -> tuple[dict, Counter | None]:
    path = config.metadata_path
    if path is None or not path.is_file():
        raise InspectionError("The metadata file does not exist or is not a file.")
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            delimiter = config.delimiter or _detect_delimiter(handle.readline())
            handle.seek(0)
            return _read_metadata(csv.reader(handle, delimiter=delimiter), delimiter, config)
    except (OSError, csv.Error) as exc:
        # The message is deliberately not included: it could contain part of a row.
        raise InspectionError("The metadata file could not be read.") from exc


def _read_metadata(reader, delimiter: str, config: InspectionConfig) -> tuple[dict, Counter | None]:
    header_row = next(reader, None)
    if header_row is None:
        return {"present": True, "rows": 0, "columns": [], "missing_columns": [], "empty_file": True}, None

    header = [name.strip() for name in header_row]
    index: dict[str, int] = {}
    duplicate_headers = 0
    for position, name in enumerate(header):
        if name in index:
            duplicate_headers += 1
        else:
            index[name] = position
    column_count = len(header)

    requested = [("id", config.id_column), ("label", config.label_column), ("group", config.group_column)]
    requested += [("numeric", name) for name in config.numeric_columns]
    missing_columns = []
    for role, name in requested:
        if name and name not in index:
            suggestions = [h for h in header if _norm(h) == _norm(name)]
            missing_columns.append({"role": role, "column": name, "did_you_mean": suggestions})

    empty = [0] * column_count
    placeholder = [0] * column_count
    distinct: list[set[str]] = [set() for _ in header]
    capped = [False] * column_count

    label_i = index.get(config.label_column) if config.label_column else None
    id_i = index.get(config.id_column) if config.id_column else None
    group_i = index.get(config.group_column) if config.group_column else None
    numeric_i = {name: index[name] for name in config.numeric_columns if name in index}

    label_counter: Counter = Counter()
    labels_per_row: Counter = Counter()
    rows_without_label = 0
    id_counter: Counter = Counter()
    rows_without_id = 0
    group_counter: Counter = Counter()
    rows_without_group = 0
    numeric_values: dict[str, list[float]] = {name: [] for name in numeric_i}
    numeric_bad: Counter = Counter()

    rows = malformed = 0
    for row in reader:
        if not row:  # blank line
            continue
        rows += 1
        if len(row) != column_count:
            malformed += 1
            row = (row + [""] * column_count)[:column_count]
        for position, raw in enumerate(row):
            value = raw.strip()
            if not value:
                empty[position] += 1
                continue
            if value.lower() in PLACEHOLDER_TOKENS:
                placeholder[position] += 1
            if not capped[position]:
                if len(distinct[position]) >= DISTINCT_CAP:
                    capped[position] = True
                else:
                    distinct[position].add(value)

        if label_i is not None:
            value = row[label_i].strip()
            labels = [part.strip() for part in value.split(config.label_separator)] if config.label_separator else [value]
            labels = {label for label in labels if label}
            if labels:
                label_counter.update(labels)
                labels_per_row[len(labels)] += 1
            else:
                rows_without_label += 1
        if id_i is not None:
            value = row[id_i].strip()
            if value:
                id_counter[value] += 1
            else:
                rows_without_id += 1
        if group_i is not None:
            value = row[group_i].strip()
            if value:
                group_counter[value] += 1
            else:
                rows_without_group += 1
        for name, position in numeric_i.items():
            value = row[position].strip()
            if not value:
                continue
            try:
                number = float(value)
            except ValueError:
                numeric_bad[name] += 1
                continue
            if math.isfinite(number):
                numeric_values[name].append(number)
            else:
                numeric_bad[name] += 1

    columns = [
        {
            "name": name,
            "empty": empty[position],
            "empty_fraction": round(empty[position] / rows, 4) if rows else None,
            "placeholder_like": placeholder[position],
            "distinct_values": len(distinct[position]),
            "distinct_capped": capped[position],
        }
        for position, name in enumerate(header)
    ]

    section: dict = {
        "present": True,
        "rows": rows,
        "malformed_rows": malformed,
        "delimiter": DELIMITER_NAMES.get(delimiter, delimiter),
        "duplicate_header_names": duplicate_headers,
        "column_count": column_count,
        "columns": columns,
        "missing_columns": missing_columns,
        "label": _label_section(config, label_i, label_counter, labels_per_row, rows_without_label),
        "id": None
        if id_i is None
        else {
            "column": config.id_column,
            "rows_without_id": rows_without_id,
            "distinct_ids": len(id_counter),
            "ids_repeated": sum(1 for count in id_counter.values() if count > 1),
            "extra_rows_for_repeated_ids": sum(count - 1 for count in id_counter.values() if count > 1),
        },
        "group": None
        if group_i is None
        else {
            "column": config.group_column,
            "rows_without_group": rows_without_group,
            "distinct_groups": len(group_counter),
            "groups_with_multiple_rows": sum(1 for count in group_counter.values() if count > 1),
            "rows_in_multi_row_groups": sum(count for count in group_counter.values() if count > 1),
            "max_rows_in_one_group": max(group_counter.values(), default=0),
        },
        "numeric": [
            {
                "column": name,
                "numeric_values": len(numeric_values[name]),
                "non_numeric_values": numeric_bad[name],
                **(_numeric_summary(numeric_values[name]) or {}),
            }
            for name in numeric_i
        ],
    }
    return section, (id_counter if id_i is not None else None)


def _label_section(
    config: InspectionConfig, label_i: int | None, counter: Counter, per_row: Counter, rows_without_label: int
) -> dict | None:
    if label_i is None:
        return None
    labelled_rows = sum(per_row.values())
    section: dict = {
        "column": config.label_column,
        "separator": config.label_separator,
        "rows_with_label": labelled_rows,
        "rows_without_label": rows_without_label,
        "distinct_labels": len(counter),
        "distribution": None,
        "distribution_hidden_reason": None,
        "labels_per_row": {str(k): v for k, v in sorted(per_row.items())} if config.label_separator else None,
    }
    if len(counter) > MAX_LABELS_SHOWN:
        section["distribution_hidden_reason"] = (
            f"more than {MAX_LABELS_SHOWN} distinct values; this may not be a label column"
        )
    elif any(len(label) > MAX_LABEL_LENGTH for label in counter):
        section["distribution_hidden_reason"] = (
            f"some values are longer than {MAX_LABEL_LENGTH} characters; this may be free text, not a label column"
        )
    else:
        ordered = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
        section["distribution"] = [
            {"label": label, "count": count, "fraction_of_labelled_rows": round(count / labelled_rows, 4)}
            for label, count in ordered
        ]
    return section


# ---------------------------------------------------------------- cross-check and warnings


def _cross_check(config: InspectionConfig, image_paths: list[Path], id_counter: Counter | None) -> dict | None:
    """Match metadata ids to image files. Rule: an id matches a file whose name, or whose name without
    its extension, equals the id. Only counts are reported."""
    if id_counter is None:
        return None
    names = {path.name for path in image_paths}
    stems = Counter(path.stem for path in image_paths)
    ids = set(id_counter)
    matched = sum(1 for value in ids if value in names or value in stems)
    images_without_row = sum(1 for path in image_paths if path.name not in ids and path.stem not in ids)
    return {
        "matching_rule": "metadata id equals the file name, or the file name without its extension",
        "distinct_ids": len(ids),
        "ids_with_image": matched,
        "ids_without_image": len(ids) - matched,
        "images_without_metadata_row": images_without_row,
        "image_stems_shared_by_several_files": sum(1 for count in stems.values() if count > 1),
    }


def _collect_warnings(summary: dict) -> list[str]:
    found: list[str] = []
    images, metadata, cross = summary["images"], summary["metadata"], summary["cross_check"]
    if images["checked"] == 0:
        found.append("No image files were found in the image folder (check the folder and the image extensions).")
    if images["corrupt"]:
        found.append(f"{images['corrupt']} image file(s) could not be decoded (corrupt or truncated).")
    if images["too_large"]:
        found.append(f"{images['too_large']} image file(s) exceed the safe pixel limit and were not decoded.")
    if images["unreadable"]:
        found.append(f"{images['unreadable']} image file(s) could not be read (permissions or I/O error).")
    if images["duplicates"]["extra_copies"]:
        found.append(
            f"{images['duplicates']['extra_copies']} image file(s) are exact byte-for-byte copies of another file."
        )
    if metadata is not None:
        if metadata.get("empty_file") or metadata["rows"] == 0:
            found.append("The metadata file has no data rows.")
        if metadata.get("column_count") == 1:
            found.append("Only one column was found in the metadata file; the delimiter may be wrong (use --delimiter).")
        if metadata.get("missing_columns"):
            names = ", ".join(item["column"] for item in metadata["missing_columns"])
            found.append(f"Configured column(s) not found in the metadata header: {names}. Dependent checks were skipped.")
        if metadata.get("malformed_rows"):
            found.append(f"{metadata['malformed_rows']} metadata row(s) have a different number of cells than the header.")
        if metadata.get("duplicate_header_names"):
            found.append("The metadata header contains repeated column names; only the first of each was used.")
        if metadata.get("id") and metadata["id"]["extra_rows_for_repeated_ids"]:
            found.append(
                f"{metadata['id']['ids_repeated']} id value(s) appear in more than one metadata row."
            )
        group = metadata.get("group")
        if group and group["groups_with_multiple_rows"]:
            found.append(
                f"{group['groups_with_multiple_rows']} group(s) have several rows. Split train/validation/test by "
                f"'{group['column']}', not by row or image, to avoid leakage."
            )
    if cross:
        if cross["ids_without_image"]:
            found.append(f"{cross['ids_without_image']} metadata id(s) have no matching image file.")
        if cross["images_without_metadata_row"]:
            found.append(f"{cross['images_without_metadata_row']} image file(s) have no matching metadata row.")
        if cross["distinct_ids"] and images["checked"] and not cross["ids_with_image"]:
            found.append(
                "No metadata id matched any image file. The id column may be wrong, or ids and file names follow a "
                "different pattern; this tool only matches an id to a file name or a file name without extension."
            )
    return found
