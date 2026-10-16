"""Tesseract wrapper tests. The last group runs the real Tesseract and is skipped if it is not installed."""

import shutil
import subprocess

import pytest

from lumi.eval.synthetic_lab_reports import render_lab_report
from lumi.pipelines.ocr import engine as engine_module
from lumi.pipelines.ocr.engine import OcrFailedError, OcrUnavailableError, TesseractEngine, parse_tsv

requires_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")

TSV_HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def tsv_word(line: int, word: int, conf: float, text: str) -> str:
    return f"5\t1\t1\t1\t{line}\t{word}\t0\t0\t10\t10\t{conf}\t{text}"


def test_parse_tsv_groups_words_into_lines_with_mean_confidence():
    tsv = "\n".join(
        [
            TSV_HEADER,
            "1\t1\t0\t0\t0\t0\t0\t0\t100\t100\t-1\t",  # page-level row, ignored
            tsv_word(1, 1, 90, "Sodium"),
            tsv_word(1, 2, 80, "139"),
            tsv_word(2, 1, 70, "Glucose"),
            tsv_word(2, 2, -1, " "),  # empty word, ignored
        ]
    )
    lines = parse_tsv(tsv)
    assert [line.text for line in lines] == ["Sodium 139", "Glucose"]
    assert [line.confidence for line in lines] == [85.0, 70.0]


def test_parse_tsv_handles_empty_output():
    assert parse_tsv("") == []
    assert parse_tsv(TSV_HEADER) == []


def test_missing_binary_raises_unavailable():
    with pytest.raises(OcrUnavailableError):
        TesseractEngine(binary="definitely-not-installed-ocr").extract(render_lab_report()[0])


def test_timeout_raises_unavailable(monkeypatch):
    def slow_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="tesseract", timeout=1)

    monkeypatch.setattr(engine_module.subprocess, "run", slow_run)
    with pytest.raises(OcrUnavailableError):
        TesseractEngine().extract(render_lab_report()[0])


def test_nonzero_exit_raises_failed_without_stderr(monkeypatch):
    def failing_run(args, **kwargs):
        return subprocess.CompletedProcess(args, returncode=1, stdout=b"", stderr=b"Haemoglobin 12.1")

    monkeypatch.setattr(engine_module.subprocess, "run", failing_run)
    with pytest.raises(OcrFailedError) as excinfo:
        TesseractEngine().extract(render_lab_report()[0])
    assert "Haemoglobin" not in str(excinfo.value)


@requires_tesseract
def test_real_tesseract_reads_synthetic_report():
    image, _ = render_lab_report()
    result = TesseractEngine().extract(image)
    assert "Haemoglobin" in result.text
    assert result.engine_name == "tesseract"
    assert result.engine_version[0].isdigit()
    assert result.mean_confidence is not None
