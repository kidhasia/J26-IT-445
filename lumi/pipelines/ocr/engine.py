"""Local OCR using the Tesseract command-line program.

The image is piped to Tesseract through stdin and results come back through stdout,
so report contents are never written to temporary files and never leave this machine.
"""

import subprocess
from dataclasses import dataclass
from functools import cached_property
from io import BytesIO
from typing import Protocol

from PIL import Image, ImageOps


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float | None  # mean Tesseract word confidence, 0-100; None if unknown


@dataclass(frozen=True)
class OcrResult:
    lines: list[OcrLine]
    engine_name: str
    engine_version: str
    language: str

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def mean_confidence(self) -> float | None:
        values = [line.confidence for line in self.lines if line.confidence is not None]
        return round(sum(values) / len(values), 1) if values else None


class OcrUnavailableError(Exception):
    """The OCR engine is missing or did not finish in time."""


class OcrFailedError(Exception):
    """The OCR engine ran but reported an error."""


class OcrEngine(Protocol):
    def extract(self, image_bytes: bytes) -> OcrResult: ...


def prepare_image(image_bytes: bytes) -> bytes:
    """Rotate phone photos upright (EXIF) and convert to greyscale PNG for Tesseract."""
    with Image.open(BytesIO(image_bytes)) as img:
        prepared = ImageOps.exif_transpose(img).convert("L")
    buf = BytesIO()
    prepared.save(buf, format="PNG")
    return buf.getvalue()


def parse_tsv(tsv: str) -> list[OcrLine]:
    """Group Tesseract's word-level TSV output into text lines, in reading order."""
    rows = tsv.splitlines()
    if not rows:
        return []
    header = rows[0].split("\t")
    col = {name: i for i, name in enumerate(header)}
    lines: dict[tuple[str, ...], list[tuple[str, float]]] = {}
    for row in rows[1:]:
        cells = row.split("\t")
        if len(cells) < len(header) or cells[col["level"]] != "5":  # level 5 = a single word
            continue
        word = cells[col["text"]].strip()
        if not word:
            continue
        key = tuple(cells[col[name]] for name in ("page_num", "block_num", "par_num", "line_num"))
        lines.setdefault(key, []).append((word, float(cells[col["conf"]])))
    result = []
    for words in lines.values():
        confidences = [conf for _, conf in words if conf >= 0]
        mean = round(sum(confidences) / len(confidences), 1) if confidences else None
        result.append(OcrLine(text=" ".join(word for word, _ in words), confidence=mean))
    return result


class TesseractEngine:
    def __init__(self, binary: str = "tesseract", language: str = "eng", page_mode: int = 6, timeout_seconds: float = 30):
        self.binary = binary
        self.language = language
        self.page_mode = page_mode  # 6 = "assume a single uniform block of text", suits table-like reports
        self.timeout_seconds = timeout_seconds

    @cached_property
    def version(self) -> str:
        output = self._run(["--version"], b"").stdout.decode("utf-8", "replace")
        first_line = output.splitlines()[0] if output else ""
        return first_line.removeprefix("tesseract ").strip() or "unknown"

    def extract(self, image_bytes: bytes) -> OcrResult:
        args = ["stdin", "stdout", "-l", self.language, "--psm", str(self.page_mode), "tsv"]
        completed = self._run(args, prepare_image(image_bytes))
        return OcrResult(
            lines=parse_tsv(completed.stdout.decode("utf-8", "replace")),
            engine_name="tesseract",
            engine_version=self.version,
            language=self.language,
        )

    def _run(self, args: list[str], stdin: bytes) -> subprocess.CompletedProcess:
        try:
            completed = subprocess.run(
                [self.binary, *args], input=stdin, capture_output=True, timeout=self.timeout_seconds
            )
        except FileNotFoundError as exc:
            raise OcrUnavailableError(f"OCR program '{self.binary}' is not installed.") from exc
        except subprocess.TimeoutExpired as exc:
            raise OcrUnavailableError(f"OCR did not finish within {self.timeout_seconds} seconds.") from exc
        if completed.returncode != 0:
            # stderr is deliberately not included: keep engine output out of error messages and logs.
            raise OcrFailedError(f"OCR program exited with code {completed.returncode}.")
        return completed
