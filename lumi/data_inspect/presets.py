"""Optional column-name presets for datasets named in the proposal.

A preset only supplies DEFAULT names. They are always checked against the real file header at run
time, and any mismatch is reported (never silently accepted), so a wrong preset cannot produce
misleading results. Command-line options override preset values.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    description: str
    provenance: str
    id_column: str | None = None
    label_column: str | None = None
    label_separator: str | None = None
    group_column: str | None = None
    numeric_columns: tuple[str, ...] = ()


PRESETS: dict[str, Preset] = {
    "ham10000": Preset(
        description="HAM10000 metadata (HAM10000_metadata.tab on Harvard Dataverse; tab-separated there)",
        provenance=(
            "Official Dataverse record (doi:10.7910/DVN/DBW86T, read 2026-10-16) names only `lesion_id`. The other "
            "names come from secondary sources, not the official page. All are checked against the real header."
        ),
        id_column="image_id",
        label_column="dx",
        group_column="lesion_id",
        numeric_columns=("age",),
    ),
    "pad_ufes_20": Preset(
        description="PAD-UFES-20 metadata.csv (Mendeley Data, doi:10.17632/zr7vgbcyr2.1; comma-separated)",
        provenance=(
            "Column names match the paper's Table 1 (Data in Brief 32:106221) and were confirmed against the real "
            "downloaded header on 2026-10-18 (26 columns, 2,298 rows)."
        ),
        id_column="img_id",
        label_column="diagnostic",
        group_column="patient_id",
        numeric_columns=("age", "diameter_1", "diameter_2"),
    ),
    "nih_cxr14": Preset(
        description="NIH ChestX-ray14 metadata (Data_Entry_2017 / Data_Entry_2017_v2020 CSV)",
        provenance=(
            "Names come from third-party mirrors and papers; the official NIH README was not read. "
            "All are checked against the real header."
        ),
        id_column="Image Index",
        label_column="Finding Labels",
        label_separator="|",
        group_column="Patient ID",
        numeric_columns=("Patient Age", "Follow-up #"),
    ),
}
