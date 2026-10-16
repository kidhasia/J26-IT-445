"""Command line for the dataset inspector.

Example:
    .venv/bin/python -m lumi.data_inspect --name ham --images data/raw/HAM10000 \
        --metadata data/raw/HAM10000/HAM10000_metadata.tab --preset ham10000
"""

import argparse
import json
import re
import sys
from pathlib import Path

from lumi.data_inspect.inspector import DELIMITER_NAMES, InspectionConfig, InspectionError, inspect_dataset
from lumi.data_inspect.presets import PRESETS
from lumi.data_inspect.report import render_markdown

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "processed" / "inspection"
_NAMED_DELIMITERS = {name: char for char, name in DELIMITER_NAMES.items()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m lumi.data_inspect",
        description="Read-only dataset inspection. Writes <name>_summary.json and <name>_report.md; prints counts only.",
    )
    parser.add_argument("--name", required=True, help="Short name for the dataset; used in the output file names.")
    parser.add_argument("--images", required=True, help="Folder containing the image files (searched recursively).")
    parser.add_argument("--metadata", help="Optional metadata file (CSV/TSV).")
    parser.add_argument("--preset", choices=sorted(PRESETS), help="Default column names for a known dataset.")
    parser.add_argument("--delimiter", help="tab, comma, semicolon or one character. Default: detect from the header.")
    parser.add_argument("--id-column", help="Column holding the image id or file name.")
    parser.add_argument("--label-column", help="Column holding the label(s).")
    parser.add_argument("--label-separator", help="Separator when one cell holds several labels, e.g. '|'.")
    parser.add_argument("--group-column", help="Patient or lesion id column, used to warn about split leakage.")
    parser.add_argument("--numeric-column", action="append", help="Numeric column to summarise (repeatable).")
    parser.add_argument("--extensions", default=".jpg,.jpeg,.png", help="Image extensions, comma-separated.")
    parser.add_argument(
        "--check-level",
        choices=["full", "header"],
        default="full",
        help="full decodes every image (thorough, slower); header only checks that files open.",
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Where to write the report files.")
    parser.add_argument(
        "--list-problem-files",
        action="store_true",
        help="Also write <name>_problem_files.txt (relative paths of corrupt and duplicate files). Local use only.",
    )
    return parser


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _parse_delimiter(value: str | None) -> str | None:
    if value is None:
        return None
    if value.lower() in _NAMED_DELIMITERS:
        return _NAMED_DELIMITERS[value.lower()]
    if len(value) == 1:
        return value
    raise InspectionError("--delimiter must be tab, comma, semicolon or a single character.")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    preset = PRESETS.get(args.preset) if args.preset else None
    pick = lambda cli_value, preset_value: cli_value if cli_value is not None else preset_value  # noqa: E731

    try:
        config = InspectionConfig(
            name=args.name,
            image_dir=Path(args.images),
            metadata_path=Path(args.metadata) if args.metadata else None,
            delimiter=_parse_delimiter(args.delimiter),
            id_column=pick(args.id_column, preset.id_column if preset else None),
            label_column=pick(args.label_column, preset.label_column if preset else None),
            label_separator=pick(args.label_separator, preset.label_separator if preset else None),
            group_column=pick(args.group_column, preset.group_column if preset else None),
            numeric_columns=tuple(args.numeric_column or (preset.numeric_columns if preset else ())),
            image_extensions=tuple(
                ext.strip().lower() if ext.strip().startswith(".") else "." + ext.strip().lower()
                for ext in args.extensions.split(",")
                if ext.strip()
            ),
            check_level=args.check_level,
            config_source=f"preset '{args.preset}' plus command-line overrides" if preset else "command line",
        )
        output_dir = Path(args.output_dir)
        if _inside(output_dir, config.image_dir) or (
            config.metadata_path and output_dir.resolve() == config.metadata_path.resolve().parent
        ):
            raise InspectionError("The output folder must not be inside the dataset folder; source data is never modified.")

        def progress(done: int, total: int) -> None:
            print(f"  checked {done}/{total} images", file=sys.stderr)

        result = inspect_dataset(config, progress)
    except InspectionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", args.name)
    summary_path = output_dir / f"{safe_name}_summary.json"
    report_path = output_dir / f"{safe_name}_report.md"
    summary_path.write_text(json.dumps(result.summary, indent=2, sort_keys=False) + "\n")
    report_path.write_text(render_markdown(result.summary))

    summary = result.summary
    print(f"Images checked: {summary['images']['checked']} (ok {summary['images']['ok']}, "
          f"corrupt {summary['images']['corrupt']}, duplicate copies {summary['images']['duplicates']['extra_copies']})")
    if summary["metadata"] and not summary["metadata"].get("empty_file"):
        print(f"Metadata rows: {summary['metadata']['rows']}")
    print(f"Warnings: {len(summary['warnings'])}")
    for warning in summary["warnings"]:
        print(f"  - {warning}")
    print(f"Wrote {summary_path}\nWrote {report_path}")
    if args.list_problem_files:
        problem_path = output_dir / f"{safe_name}_problem_files.txt"
        lines = [f"{kind}\t{path}" for kind, paths in result.problem_files.items() for path in paths]
        problem_path.write_text("\n".join(lines) + ("\n" if lines else ""))
        print(f"Wrote {problem_path} (contains file paths; keep it local)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
