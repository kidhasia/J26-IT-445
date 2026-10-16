"""Render the inspection summary as a human-readable Markdown report. Uses only values already in the summary."""


def _cell(value) -> str:
    return "" if value is None else str(value).replace("|", "\\|")


def _table(headers: list[str], rows: list[list]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows]
    return lines + [""]


def render_markdown(summary: dict) -> str:
    cfg, files, images = summary["config"], summary["files"], summary["images"]
    out: list[str] = [
        f"# Dataset inspection report: {summary['dataset_name']}",
        "",
        f"Generated {summary['generated_at']} by {summary['tool']['name']} v{summary['tool']['version']}.",
        "",
        f"> {summary['privacy_note']}",
        "",
        "## Warnings",
        "",
    ]
    out += [f"- {warning}" for warning in summary["warnings"]] or ["None."]
    out += ["", "## Configuration", ""]
    out += _table(
        ["Setting", "Value"],
        [
            ["Where settings came from", cfg["config_source"]],
            ["Image folder (name only)", cfg["image_folder_name"]],
            ["Metadata file (name only)", cfg["metadata_file_name"] or "none given"],
            ["Image extensions", ", ".join(cfg["image_extensions"])],
            ["Image check level", cfg["check_level"]],
            ["Id column", cfg["id_column"]],
            ["Label column", cfg["label_column"]],
            ["Label separator", cfg["label_separator"]],
            ["Group column", cfg["group_column"]],
            ["Numeric columns", ", ".join(cfg["numeric_columns"])],
        ],
    )

    out += ["## Files", ""]
    out += _table(
        ["Measure", "Count"],
        [
            ["All files", files["total_files"]],
            ["Image files", files["image_files"]],
            ["Other files", files["non_image_files"]],
            ["Hidden files skipped", files["hidden_files_skipped"]],
        ],
    )
    out += _table(["Extension", "Files"], [[ext, n] for ext, n in files["by_extension"].items()])

    out += ["## Images", ""]
    out += _table(
        ["Measure", "Count"],
        [
            ["Checked", images["checked"]],
            ["OK", images["ok"]],
            ["Corrupt / truncated", images["corrupt"]],
            ["Over pixel limit", images["too_large"]],
            ["Unreadable (I/O)", images["unreadable"]],
        ],
    )
    if images["check_level"] == "header":
        out += ["Check level is `header`: truncated files may not be detected. Use `full` for a thorough check.", ""]
    dims = images["dimensions"]
    if dims:
        out += ["### Dimensions (pixels)", ""]
        out += _table(
            ["", "Min", "Median", "Mean", "Max"],
            [[name, d["min"], d["median"], d["mean"], d["max"]] for name, d in (("Width", dims["width"]), ("Height", dims["height"]))],
        )
        out += [f"Distinct sizes: {dims['distinct_sizes']}", ""]
        out += _table(["Most common size", "Images"], [[s["size"], s["count"]] for s in dims["most_common_sizes"]])
        out += _table(["Colour mode", "Images"], [[m, n] for m, n in dims["color_modes"].items()])
        out += _table(["Format", "Images"], [[f, n] for f, n in dims["formats"].items()])
    dup = images["duplicates"]
    out += ["### Exact duplicates (same bytes)", ""]
    out += _table(
        ["Measure", "Count"],
        [
            ["Duplicate groups", dup["duplicate_groups"]],
            ["Files in those groups", dup["files_in_duplicate_groups"]],
            ["Extra copies", dup["extra_copies"]],
            ["Largest group", dup["largest_group"]],
        ],
    )

    metadata = summary["metadata"]
    out += ["## Metadata", ""]
    if metadata is None:
        out += ["No metadata file was given.", ""]
    elif metadata.get("empty_file"):
        out += ["The metadata file is empty.", ""]
    else:
        out += [
            f"Rows: {metadata['rows']}. Columns: {metadata['column_count']}. Delimiter: {metadata['delimiter']}. "
            f"Rows with the wrong number of cells: {metadata['malformed_rows']}.",
            "",
        ]
        if metadata["missing_columns"]:
            out += ["### Configured columns NOT found in the header", ""]
            out += _table(
                ["Role", "Configured name", "Did you mean"],
                [[m["role"], m["column"], ", ".join(m["did_you_mean"]) or "(no close match)"] for m in metadata["missing_columns"]],
            )
            out += ["Available columns: " + ", ".join(f"`{c['name']}`" for c in metadata["columns"]), ""]
        out += ["### Missing values per column", ""]
        out += _table(
            ["Column", "Empty", "Empty %", "Placeholder-like*", "Distinct values"],
            [
                [
                    c["name"],
                    c["empty"],
                    "" if c["empty_fraction"] is None else f"{c['empty_fraction'] * 100:.1f}",
                    c["placeholder_like"],
                    f">={c['distinct_values']}" if c["distinct_capped"] else c["distinct_values"],
                ]
                for c in metadata["columns"]
            ],
        )
        out += ["*Values such as NA, null, none, unknown, ?, -. They are listed separately and are not removed or hidden.", ""]

        label = metadata["label"]
        if label:
            out += [f"### Labels (column `{label['column']}`)", ""]
            out += [
                f"Rows with a label: {label['rows_with_label']}. Rows without: {label['rows_without_label']}. "
                f"Distinct labels: {label['distinct_labels']}.",
                "",
            ]
            if label["distribution"] is not None:
                out += _table(
                    ["Label", "Count", "Share of labelled rows"],
                    [[d["label"], d["count"], f"{d['fraction_of_labelled_rows'] * 100:.1f}%"] for d in label["distribution"]],
                )
            else:
                out += [f"Label values are not listed: {label['distribution_hidden_reason']}.", ""]
            if label["labels_per_row"]:
                out += _table(["Labels in one row", "Rows"], [[k, v] for k, v in label["labels_per_row"].items()])
        ident = metadata["id"]
        if ident:
            out += [f"### Ids (column `{ident['column']}`)", ""]
            out += _table(
                ["Measure", "Count"],
                [
                    ["Distinct ids", ident["distinct_ids"]],
                    ["Rows without an id", ident["rows_without_id"]],
                    ["Ids appearing in more than one row", ident["ids_repeated"]],
                ],
            )
        group = metadata["group"]
        if group:
            out += [f"### Groups (column `{group['column']}`)", ""]
            out += _table(
                ["Measure", "Count"],
                [
                    ["Distinct groups", group["distinct_groups"]],
                    ["Rows without a group", group["rows_without_group"]],
                    ["Groups with several rows", group["groups_with_multiple_rows"]],
                    ["Rows in those groups", group["rows_in_multi_row_groups"]],
                    ["Most rows in one group", group["max_rows_in_one_group"]],
                ],
            )
        if metadata["numeric"]:
            out += ["### Numeric columns", ""]
            out += _table(
                ["Column", "Numeric values", "Non-numeric", "Min", "Median", "Mean", "Max"],
                [[n["column"], n["numeric_values"], n["non_numeric_values"], n.get("min"), n.get("median"), n.get("mean"), n.get("max")] for n in metadata["numeric"]],
            )

    cross = summary["cross_check"]
    if cross:
        out += ["## Metadata and image files", "", f"Matching rule: {cross['matching_rule']}.", ""]
        out += _table(
            ["Measure", "Count"],
            [
                ["Distinct metadata ids", cross["distinct_ids"]],
                ["Ids with an image", cross["ids_with_image"]],
                ["Ids without an image", cross["ids_without_image"]],
                ["Images without a metadata row", cross["images_without_metadata_row"]],
            ],
        )
    return "\n".join(out).rstrip() + "\n"
