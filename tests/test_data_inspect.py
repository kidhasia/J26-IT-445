"""Dataset inspector tests. All data is generated in tmp folders; no real dataset is used."""

import hashlib
import json
import random
from pathlib import Path

import pytest
from PIL import Image

from lumi.data_inspect.cli import main
from lumi.data_inspect.inspector import InspectionConfig, InspectionError, inspect_dataset
from lumi.data_inspect.report import render_markdown


# ---------------------------------------------------------------- helpers


def make_image(path: Path, size=(20, 10), color=(10, 20, 30), fmt="PNG") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format=fmt)
    return path


def make_noise_jpeg(path: Path, size=(64, 64)) -> Path:
    rng = random.Random(0)
    Image.frombytes("RGB", size, bytes(rng.randrange(256) for _ in range(size[0] * size[1] * 3))).save(path, format="JPEG")
    return path


def write_metadata(path: Path, header: list[str], rows: list[list[str]], delimiter: str = ",") -> Path:
    lines = [delimiter.join(header)] + [delimiter.join(row) for row in rows]
    path.write_text("\n".join(lines) + "\n")
    return path


def config(tmp_path: Path, **overrides) -> InspectionConfig:
    values = {"name": "test", "image_dir": tmp_path / "images"}
    values.update(overrides)
    return InspectionConfig(**values)


@pytest.fixture
def images_dir(tmp_path) -> Path:
    path = tmp_path / "images"
    path.mkdir()
    return path


def tree_fingerprint(root: Path) -> dict:
    return {
        p.relative_to(root).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# ---------------------------------------------------------------- empty and missing inputs


def test_empty_image_folder_gives_zero_counts_and_a_warning(tmp_path, images_dir):
    summary = inspect_dataset(config(tmp_path)).summary
    assert summary["images"]["checked"] == 0
    assert summary["images"]["dimensions"] is None
    assert summary["files"]["total_files"] == 0
    assert any("No image files" in w for w in summary["warnings"])
    json.dumps(summary)
    assert "No image files" in render_markdown(summary)


def test_missing_image_folder_is_an_error(tmp_path):
    with pytest.raises(InspectionError):
        inspect_dataset(config(tmp_path))


def test_missing_metadata_file_is_an_error(tmp_path, images_dir):
    with pytest.raises(InspectionError):
        inspect_dataset(config(tmp_path, metadata_path=tmp_path / "nope.csv"))


def test_empty_metadata_file_is_reported_not_crashed(tmp_path, images_dir):
    metadata = tmp_path / "meta.csv"
    metadata.write_text("")
    summary = inspect_dataset(config(tmp_path, metadata_path=metadata)).summary
    assert summary["metadata"]["empty_file"] is True
    assert any("no data rows" in w for w in summary["warnings"])
    render_markdown(summary)


def test_header_only_metadata_has_zero_rows(tmp_path, images_dir):
    metadata = write_metadata(tmp_path / "meta.csv", ["image_id", "dx"], [])
    summary = inspect_dataset(config(tmp_path, metadata_path=metadata, label_column="dx")).summary
    assert summary["metadata"]["rows"] == 0
    assert summary["metadata"]["label"]["distribution"] == []


# ---------------------------------------------------------------- missing columns


def test_missing_columns_are_reported_with_suggestions_and_other_checks_still_run(tmp_path, images_dir):
    make_image(images_dir / "a.png")
    metadata = write_metadata(tmp_path / "meta.csv", ["Image_ID", "Diagnosis"], [["a", "x"], ["b", "y"]])
    summary = inspect_dataset(
        config(tmp_path, metadata_path=metadata, id_column="image id", label_column="dx", group_column="lesion_id")
    ).summary
    missing = {m["column"]: m for m in summary["metadata"]["missing_columns"]}
    assert set(missing) == {"image id", "dx", "lesion_id"}
    assert missing["image id"]["did_you_mean"] == ["Image_ID"]  # same name apart from case and punctuation
    assert missing["dx"]["did_you_mean"] == []
    assert summary["metadata"]["label"] is None and summary["metadata"]["id"] is None and summary["metadata"]["group"] is None
    assert summary["cross_check"] is None
    assert summary["images"]["checked"] == 1  # image checks were not skipped
    assert summary["metadata"]["rows"] == 2
    assert any("not found in the metadata header" in w for w in summary["warnings"])
    assert "Did you mean" in render_markdown(summary)


def test_missing_numeric_column_is_reported(tmp_path, images_dir):
    metadata = write_metadata(tmp_path / "meta.csv", ["image_id"], [["a"]])
    summary = inspect_dataset(config(tmp_path, metadata_path=metadata, numeric_columns=("age",))).summary
    assert [m["role"] for m in summary["metadata"]["missing_columns"]] == ["numeric"]
    assert summary["metadata"]["numeric"] == []


def test_wrong_delimiter_is_flagged(tmp_path, images_dir):
    metadata = write_metadata(tmp_path / "meta.csv", ["image_id", "dx"], [["a", "x"]], delimiter=",")
    summary = inspect_dataset(config(tmp_path, metadata_path=metadata, delimiter="\t")).summary
    assert summary["metadata"]["column_count"] == 1
    assert any("delimiter may be wrong" in w for w in summary["warnings"])


# ---------------------------------------------------------------- metadata statistics


@pytest.mark.parametrize("delimiter, name", [("\t", "tab"), (",", "comma"), (";", "semicolon")])
def test_delimiter_is_detected(tmp_path, images_dir, delimiter, name):
    metadata = write_metadata(tmp_path / "meta.csv", ["image_id", "dx", "age"], [["a", "x", "5"]], delimiter)
    summary = inspect_dataset(config(tmp_path, metadata_path=metadata)).summary
    assert summary["metadata"]["delimiter"] == name
    assert summary["metadata"]["column_count"] == 3


def test_missing_and_placeholder_values_are_counted_separately(tmp_path, images_dir):
    metadata = write_metadata(
        tmp_path / "meta.csv",
        ["image_id", "sex"],
        [["a", "male"], ["b", ""], ["c", "unknown"], ["d", "NA"], ["e", "  "]],
    )
    column = {c["name"]: c for c in inspect_dataset(config(tmp_path, metadata_path=metadata)).summary["metadata"]["columns"]}["sex"]
    assert column["empty"] == 2
    assert column["placeholder_like"] == 2
    assert column["distinct_values"] == 3  # male, unknown, NA
    assert column["empty_fraction"] == 0.4


def test_malformed_rows_are_counted(tmp_path, images_dir):
    metadata = tmp_path / "meta.csv"
    metadata.write_text("image_id,dx\na,x\nb\nc,y,extra\n")
    summary = inspect_dataset(config(tmp_path, metadata_path=metadata)).summary
    assert summary["metadata"]["rows"] == 3
    assert summary["metadata"]["malformed_rows"] == 2


def test_single_label_distribution(tmp_path, images_dir):
    metadata = write_metadata(tmp_path / "meta.csv", ["image_id", "dx"], [["1", "nv"], ["2", "nv"], ["3", "mel"], ["4", ""]])
    label = inspect_dataset(config(tmp_path, metadata_path=metadata, label_column="dx")).summary["metadata"]["label"]
    assert label["rows_with_label"] == 3 and label["rows_without_label"] == 1
    assert [(d["label"], d["count"]) for d in label["distribution"]] == [("nv", 2), ("mel", 1)]
    assert label["distribution"][0]["fraction_of_labelled_rows"] == 0.6667
    assert label["labels_per_row"] is None


def test_multi_label_distribution(tmp_path, images_dir):
    metadata = write_metadata(
        tmp_path / "meta.csv",
        ["id", "labels"],
        [["1", "Effusion|Mass"], ["2", "No Finding"], ["3", "Effusion"], ["4", "Mass|Mass"]],
    )
    label = inspect_dataset(config(tmp_path, metadata_path=metadata, label_column="labels", label_separator="|")).summary[
        "metadata"
    ]["label"]
    assert {d["label"]: d["count"] for d in label["distribution"]} == {"Effusion": 2, "Mass": 2, "No Finding": 1}
    assert label["labels_per_row"] == {"1": 3, "2": 1}  # "Mass|Mass" counts once


def test_label_values_are_hidden_when_column_does_not_look_like_labels(tmp_path, images_dir):
    rows = [[str(i), f"value-{i}"] for i in range(60)]
    metadata = write_metadata(tmp_path / "meta.csv", ["id", "dx"], rows)
    summary = inspect_dataset(config(tmp_path, metadata_path=metadata, label_column="dx")).summary
    label = summary["metadata"]["label"]
    assert label["distribution"] is None and label["distinct_labels"] == 60
    assert "value-7" not in json.dumps(summary)
    assert "value-7" not in render_markdown(summary)


def test_long_free_text_label_values_are_hidden(tmp_path, images_dir):
    metadata = write_metadata(tmp_path / "meta.csv", ["id", "dx"], [["1", "x" * 80]])
    summary = inspect_dataset(config(tmp_path, metadata_path=metadata, label_column="dx")).summary
    assert summary["metadata"]["label"]["distribution"] is None
    assert "x" * 80 not in json.dumps(summary)


def test_id_and_group_statistics(tmp_path, images_dir):
    metadata = write_metadata(
        tmp_path / "meta.csv",
        ["image_id", "lesion_id"],
        [["i1", "L1"], ["i2", "L1"], ["i2", "L2"], ["i3", ""], ["", "L3"]],
    )
    summary = inspect_dataset(config(tmp_path, metadata_path=metadata, id_column="image_id", group_column="lesion_id")).summary
    ident, group = summary["metadata"]["id"], summary["metadata"]["group"]
    assert (ident["distinct_ids"], ident["rows_without_id"], ident["ids_repeated"]) == (3, 1, 1)
    assert (group["distinct_groups"], group["rows_without_group"]) == (3, 1)
    assert (group["groups_with_multiple_rows"], group["rows_in_multi_row_groups"], group["max_rows_in_one_group"]) == (1, 2, 2)
    assert any("Split train/validation/test by 'lesion_id'" in w for w in summary["warnings"])


def test_numeric_summary_ignores_empty_and_flags_non_numeric(tmp_path, images_dir):
    metadata = write_metadata(tmp_path / "meta.csv", ["id", "age"], [["1", "10"], ["2", "20"], ["3", ""], ["4", "abc"], ["5", "nan"]])
    (age,) = inspect_dataset(config(tmp_path, metadata_path=metadata, numeric_columns=("age",))).summary["metadata"]["numeric"]
    assert (age["numeric_values"], age["non_numeric_values"]) == (2, 2)
    assert (age["min"], age["max"], age["mean"], age["median"]) == (10.0, 20.0, 15.0, 15.0)


# ---------------------------------------------------------------- files and images


def test_file_counts_extensions_and_hidden_files(tmp_path, images_dir):
    make_image(images_dir / "a.png")
    make_image(images_dir / "sub" / "b.JPG", fmt="JPEG")
    (images_dir / "notes.txt").write_text("x")
    (images_dir / ".DS_Store").write_text("x")
    files = inspect_dataset(config(tmp_path)).summary["files"]
    assert files["total_files"] == 3 and files["image_files"] == 2 and files["non_image_files"] == 1
    assert files["hidden_files_skipped"] == 1
    assert files["by_extension"] == {".jpg": 1, ".png": 1, ".txt": 1}


def test_dimension_statistics(tmp_path, images_dir):
    make_image(images_dir / "a.png", (10, 20), color=(1, 1, 1))
    make_image(images_dir / "b.png", (10, 20), color=(2, 2, 2))
    make_image(images_dir / "c.png", (30, 40), color=(3, 3, 3))
    images = inspect_dataset(config(tmp_path)).summary["images"]
    dims = images["dimensions"]
    assert images["ok"] == 3
    assert (dims["width"]["min"], dims["width"]["max"]) == (10, 30)
    assert (dims["height"]["min"], dims["height"]["max"]) == (20, 40)
    assert dims["most_common_sizes"][0] == {"size": "10x20", "count": 2}
    assert dims["distinct_sizes"] == 2
    assert dims["color_modes"] == {"RGB": 3} and dims["formats"] == {"PNG": 3}


def test_corrupt_images_are_detected(tmp_path, images_dir):
    make_image(images_dir / "good.png")
    (images_dir / "garbage.jpg").write_bytes(b"this is not an image at all")
    good = make_noise_jpeg(images_dir / "full.jpg").read_bytes()
    (images_dir / "truncated.jpg").write_bytes(good[: len(good) // 2])
    result = inspect_dataset(config(tmp_path))
    assert result.summary["images"]["ok"] == 2 and result.summary["images"]["corrupt"] == 2
    assert sorted(result.problem_files["corrupt"]) == ["garbage.jpg", "truncated.jpg"]
    assert any("2 image file(s) could not be decoded" in w for w in result.summary["warnings"])


def test_header_level_still_catches_non_images(tmp_path, images_dir):
    (images_dir / "garbage.jpg").write_bytes(b"not an image")
    make_image(images_dir / "good.png")
    images = inspect_dataset(config(tmp_path, check_level="header")).summary["images"]
    assert images["corrupt"] == 1 and images["ok"] == 1


def test_oversized_image_is_not_decoded(tmp_path, images_dir, monkeypatch):
    make_image(images_dir / "big.png", (20, 20))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)  # 400 pixels is more than 2x this limit
    images = inspect_dataset(config(tmp_path)).summary["images"]
    assert images["too_large"] == 1 and images["ok"] == 0


def test_exact_duplicates_are_found(tmp_path, images_dir):
    original = make_image(images_dir / "a.png", color=(5, 5, 5))
    (images_dir / "a_copy.png").write_bytes(original.read_bytes())
    (images_dir / "a_copy2.png").write_bytes(original.read_bytes())
    make_image(images_dir / "other.png", color=(9, 9, 9))
    result = inspect_dataset(config(tmp_path))
    assert result.summary["images"]["duplicates"] == {
        "duplicate_groups": 1,
        "files_in_duplicate_groups": 3,
        "extra_copies": 2,
        "largest_group": 3,
    }
    assert len(result.problem_files["duplicates"]) == 3


def test_extension_list_is_configurable(tmp_path, images_dir):
    make_image(images_dir / "a.png")
    make_image(images_dir / "b.jpg", fmt="JPEG")
    assert inspect_dataset(config(tmp_path, image_extensions=(".png",))).summary["images"]["checked"] == 1


# ---------------------------------------------------------------- metadata vs files


def test_cross_check_matches_stems_and_full_names(tmp_path, images_dir):
    make_image(images_dir / "a1.jpg", fmt="JPEG")
    make_image(images_dir / "a2.png", color=(1, 1, 1))
    make_image(images_dir / "b9.png", color=(2, 2, 2))
    metadata = write_metadata(tmp_path / "meta.csv", ["image_id"], [["a1"], ["a2.png"], ["a3"]])
    summary = inspect_dataset(config(tmp_path, metadata_path=metadata, id_column="image_id")).summary
    cross = summary["cross_check"]
    assert (cross["distinct_ids"], cross["ids_with_image"], cross["ids_without_image"]) == (3, 2, 1)
    assert cross["images_without_metadata_row"] == 1
    assert any("no matching image file" in w for w in summary["warnings"])


def test_cross_check_warns_when_nothing_matches(tmp_path, images_dir):
    make_image(images_dir / "a.png")
    metadata = write_metadata(tmp_path / "meta.csv", ["image_id"], [["zzz"]])
    summary = inspect_dataset(config(tmp_path, metadata_path=metadata, id_column="image_id")).summary
    assert any("No metadata id matched any image file" in w for w in summary["warnings"])


# ---------------------------------------------------------------- privacy and safety


def build_sensitive_dataset(tmp_path: Path) -> tuple[Path, Path]:
    images = tmp_path / "dataset" / "images"
    make_image(images / "SECRETNAME_001.png", color=(1, 2, 3))
    make_image(images / "SECRETNAME_002.png", color=(4, 5, 6))
    (images / "SECRETNAME_003.png").write_bytes(b"corrupt")
    metadata = write_metadata(
        tmp_path / "dataset" / "meta.csv",
        ["image_id", "dx", "patient_name", "notes", "patient_id"],
        [
            ["SECRETNAME_001", "benign", "Jane Doe", "private note one", "PAT-778899"],
            ["SECRETNAME_002", "malignant", "John Roe", "private note two", "PAT-778899"],
            ["SECRETNAME_003", "benign", "Mary Major", "private note three", "PAT-112233"],
        ],
    )
    return images, metadata


FORBIDDEN_TEXT = ["SECRETNAME", "Jane", "John Roe", "Mary", "private note", "PAT-", "778899", "112233"]


def test_summary_and_report_contain_no_names_ids_or_row_values(tmp_path):
    images, metadata = build_sensitive_dataset(tmp_path)
    summary = inspect_dataset(
        InspectionConfig(
            name="x", image_dir=images, metadata_path=metadata, id_column="image_id", label_column="dx", group_column="patient_id"
        )
    ).summary
    text = json.dumps(summary) + render_markdown(summary)
    for forbidden in FORBIDDEN_TEXT:
        assert forbidden not in text
    assert "benign" in text and "malignant" in text  # label classes are the one allowed list of values


def test_cli_prints_and_writes_no_sensitive_values(tmp_path, capsys):
    images, metadata = build_sensitive_dataset(tmp_path)
    out = tmp_path / "out"
    code = main(["--name", "demo", "--images", str(images), "--metadata", str(metadata), "--id-column", "image_id",
                 "--label-column", "dx", "--group-column", "patient_id", "--output-dir", str(out)])
    captured = capsys.readouterr()
    assert code == 0
    written = (out / "demo_summary.json").read_text() + (out / "demo_report.md").read_text()
    for forbidden in FORBIDDEN_TEXT:
        assert forbidden not in captured.out + captured.err + written
    assert not (out / "demo_problem_files.txt").exists()  # only written when explicitly requested


def test_source_data_is_never_modified(tmp_path):
    images, metadata = build_sensitive_dataset(tmp_path)
    dataset_root = tmp_path / "dataset"
    before = tree_fingerprint(dataset_root)
    code = main(["--name", "demo", "--images", str(images), "--metadata", str(metadata), "--label-column", "dx",
                 "--output-dir", str(tmp_path / "out"), "--list-problem-files"])
    assert code == 0
    assert tree_fingerprint(dataset_root) == before  # same files, same bytes, same modification times


# ---------------------------------------------------------------- command line


def test_cli_missing_image_folder_exits_2(tmp_path, capsys):
    assert main(["--name", "x", "--images", str(tmp_path / "nope"), "--output-dir", str(tmp_path / "out")]) == 2
    assert "ERROR" in capsys.readouterr().err


def test_cli_empty_folder_completes_with_warning(tmp_path, images_dir, capsys):
    assert main(["--name", "empty", "--images", str(images_dir), "--output-dir", str(tmp_path / "out")]) == 0
    assert "No image files" in capsys.readouterr().out
    assert json.loads((tmp_path / "out" / "empty_summary.json").read_text())["images"]["checked"] == 0


def test_cli_refuses_output_inside_dataset_folder(tmp_path, images_dir, capsys):
    assert main(["--name", "x", "--images", str(images_dir), "--output-dir", str(images_dir / "reports")]) == 2
    assert not (images_dir / "reports").exists()
    assert "must not be inside the dataset folder" in capsys.readouterr().err


def test_cli_list_problem_files_writes_local_file(tmp_path, images_dir):
    (images_dir / "bad.png").write_bytes(b"nope")
    out = tmp_path / "out"
    assert main(["--name", "x", "--images", str(images_dir), "--output-dir", str(out), "--list-problem-files"]) == 0
    assert "corrupt\tbad.png" in (out / "x_problem_files.txt").read_text()


def test_cli_bad_delimiter_exits_2(tmp_path, images_dir):
    assert main(["--name", "x", "--images", str(images_dir), "--delimiter", "tabs", "--output-dir", str(tmp_path / "o")]) == 2


# ---------------------------------------------------------------- presets


HAM_HEADER = ["lesion_id", "image_id", "dx", "dx_type", "age", "sex", "localization"]


def test_ham10000_preset_with_matching_header(tmp_path, images_dir):
    make_image(images_dir / "ISIC_0000001.png")
    metadata = write_metadata(tmp_path / "ham.tab", HAM_HEADER, [["HAM_1", "ISIC_0000001", "nv", "histo", "40", "male", "back"]], "\t")
    out = tmp_path / "out"
    assert main(["--name", "ham", "--images", str(images_dir), "--metadata", str(metadata), "--preset", "ham10000", "--output-dir", str(out)]) == 0
    summary = json.loads((out / "ham_summary.json").read_text())
    assert summary["metadata"]["missing_columns"] == []
    assert summary["metadata"]["delimiter"] == "tab"
    assert summary["cross_check"]["ids_with_image"] == 1
    assert summary["metadata"]["label"]["distribution"][0]["label"] == "nv"
    assert "preset 'ham10000'" in summary["config"]["config_source"]


def test_preset_mismatch_is_reported_not_hidden(tmp_path, images_dir):
    metadata = write_metadata(tmp_path / "other.csv", ["file", "diagnosis"], [["a", "x"]])
    out = tmp_path / "out"
    assert main(["--name", "p", "--images", str(images_dir), "--metadata", str(metadata), "--preset", "ham10000", "--output-dir", str(out)]) == 0
    summary = json.loads((out / "p_summary.json").read_text())
    assert {m["column"] for m in summary["metadata"]["missing_columns"]} == {"image_id", "dx", "lesion_id", "age"}


def test_command_line_overrides_preset(tmp_path, images_dir):
    metadata = write_metadata(tmp_path / "m.csv", ["image_id", "label", "lesion_id", "age"], [["a", "x", "L", "5"]])
    out = tmp_path / "out"
    main(["--name", "o", "--images", str(images_dir), "--metadata", str(metadata), "--preset", "ham10000", "--label-column", "label", "--output-dir", str(out)])
    summary = json.loads((out / "o_summary.json").read_text())
    assert summary["metadata"]["missing_columns"] == []
    assert summary["config"]["label_column"] == "label"


def test_nih_preset_uses_pipe_separated_labels(tmp_path, images_dir):
    metadata = write_metadata(
        tmp_path / "nih.csv",
        ["Image Index", "Finding Labels", "Follow-up #", "Patient ID", "Patient Age"],
        [["00000001_000.png", "Effusion|Mass", "0", "1", "57"], ["00000002_000.png", "No Finding", "0", "2", "30"]],
    )
    out = tmp_path / "out"
    assert main(["--name", "nih", "--images", str(images_dir), "--metadata", str(metadata), "--preset", "nih_cxr14", "--output-dir", str(out)]) == 0
    summary = json.loads((out / "nih_summary.json").read_text())
    assert summary["metadata"]["missing_columns"] == []
    assert {d["label"] for d in summary["metadata"]["label"]["distribution"]} == {"Effusion", "Mass", "No Finding"}
    assert summary["metadata"]["numeric"][0]["max"] == 57.0
