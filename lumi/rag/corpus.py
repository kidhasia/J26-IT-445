"""Load the demo corpus: a manifest that lists documents, and those markdown files cut into passages.

Every passage keeps where it came from (document id, title, section, passage id, line numbers), so an answer can be
traced back to the exact place in the source file. A broken manifest raises CorpusError and the feature stays off.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

MAX_DOCUMENTS = 50
MAX_FILE_BYTES = 2_000_000
MIN_WORDS = 40  # small neighbouring blocks in one section are joined until a passage has about this many words
MIN_TAIL_WORDS = 20  # a last piece shorter than this is joined to the previous piece of the same block
MAX_WORDS = 160  # a passage never grows past this (a single longer line is cut at sentence ends)
ALLOWED_SOURCE_TYPES = ("project_document", "approved_reference")
DOC_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
REQUIRED_KEYS = ("doc_id", "title", "path", "source_type", "licence", "approved_for_medical_use")


class CorpusError(Exception):
    """The manifest or one of the listed files is missing, unsafe or malformed."""


@dataclass(frozen=True)
class Passage:
    doc_id: str
    title: str
    section: str
    passage_id: str
    line_start: int
    line_end: int
    text: str  # verbatim markdown from the source file


@dataclass(frozen=True)
class DocumentInfo:
    doc_id: str
    title: str
    path: str  # as written in the manifest
    source_type: str
    licence: str
    approved_for_medical_use: bool
    sha256: str  # of the file as loaded, so a citation names the exact version
    passages: int


@dataclass(frozen=True)
class Corpus:
    documents: tuple[DocumentInfo, ...]
    passages: tuple[Passage, ...]


def plain(text: str) -> str:
    """Markdown decoration removed, for matching and for display. Words and numbers are untouched."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # [label](link) -> label
    text = re.sub(r"[*`]+", "", text)
    text = re.sub(r"^\s*\|?\s*[-:| ]{3,}\|?\s*$", "", text, flags=re.M)  # table divider rows
    return re.sub(r"[ \t]+", " ", text).strip()


def _words(text: str) -> int:
    return len(text.split())


def _split_long_line(line: str) -> list[str]:
    """One very long line is cut at sentence ends into pieces of at most MAX_WORDS words."""
    pieces, current = [], []
    for sentence in re.split(r"(?<=[.!?])\s+", line):
        if current and _words(" ".join(current + [sentence])) > MAX_WORDS:
            pieces.append(" ".join(current))
            current = []
        current.append(sentence)
    if current:
        pieces.append(" ".join(current))
    return pieces


def split_markdown(text: str) -> list[tuple[str, int, int, str]]:
    """Return (section, first line, last line, text) for each passage. Line numbers start at 1.

    Headings (outside code blocks) set the section name. Blank lines separate blocks; tables stay in one block.
    Small blocks in the same section are joined up to MAX_WORDS; the passage text is always a contiguous piece of the file.
    """
    titles: dict[int, str] = {}
    in_code = False
    blocks: list[dict] = []  # {"section", "lines": [(number, text)]}
    current: list[tuple[int, str]] = []
    current_section = ""

    def close() -> None:
        nonlocal current
        if current:
            blocks.append({"section": current_section, "lines": current})
        current = []

    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("```"):
            in_code = not in_code
        heading = None if in_code else re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading:
            close()
            level = len(heading.group(1))
            titles = {k: v for k, v in titles.items() if k < level}
            titles[level] = plain(heading.group(2))
            current_section = " > ".join(titles[k] for k in sorted(titles))
            continue
        if not line.strip() and not in_code:
            close()
            continue
        current.append((number, line))
    close()

    passages: list[tuple[str, int, int, str]] = []
    group: list[dict] = []

    def flush() -> None:
        if not group:
            return
        lines = [pair for block in group for pair in block["lines"]]
        passages.append((group[0]["section"], lines[0][0], lines[-1][0], "\n".join(t for _, t in lines)))
        group.clear()

    for block in blocks:
        size = sum(_words(t) for _, t in block["lines"])
        if size > MAX_WORDS:  # one huge block: cut line by line, and long lines at sentence ends
            flush()
            piece: list[tuple[int, str]] = []
            for number, line in block["lines"]:
                for part in _split_long_line(line) if _words(line) > MAX_WORDS else [line]:
                    if piece and sum(_words(t) for _, t in piece) + _words(part) > MAX_WORDS:
                        passages.append((block["section"], piece[0][0], piece[-1][0], "\n".join(t for _, t in piece)))
                        piece = []
                    piece.append((number, part))
            if piece:
                tail = (block["section"], piece[0][0], piece[-1][0], "\n".join(t for _, t in piece))
                last = passages[-1] if passages else None
                if last and last[0] == block["section"] and _words(plain(tail[3])) < MIN_TAIL_WORDS and last[2] + 1 >= tail[1] and _words(last[3]) + _words(tail[3]) <= MAX_WORDS + MIN_TAIL_WORDS:
                    passages[-1] = (last[0], last[1], tail[2], last[3] + "\n" + tail[3])  # a tiny last piece is kept with the one before it
                else:
                    passages.append(tail)
            continue
        joined = sum(_words(t) for b in group for _, t in b["lines"])
        if group and (group[0]["section"] != block["section"] or joined >= MIN_WORDS or joined + size > MAX_WORDS):
            flush()
        group.append(block)
    flush()
    return [p for p in passages if _words(plain(p[3])) >= 3]


def load_corpus(manifest_path: Path, base_dir: Path | None = None) -> Corpus:
    """Read the manifest and the files it lists. Documents must sit inside `base_dir` (default: the folder that contains
    the manifest's folder), so a manifest cannot point at files elsewhere on the computer."""
    manifest_path = Path(manifest_path)
    base = (base_dir or manifest_path.resolve().parent.parent).resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CorpusError("The corpus manifest is missing or is not valid JSON.") from exc
    entries = manifest.get("documents") if isinstance(manifest, dict) else None
    if not isinstance(entries, list) or not entries:
        raise CorpusError("The manifest must contain a non-empty list called 'documents'.")
    if len(entries) > MAX_DOCUMENTS:
        raise CorpusError(f"The manifest lists more than {MAX_DOCUMENTS} documents.")

    documents: list[DocumentInfo] = []
    passages: list[Passage] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        where = f"documents[{index}]"
        if not isinstance(entry, dict):
            raise CorpusError(f"{where} must be an object.")
        missing = [key for key in REQUIRED_KEYS if key not in entry]
        if missing:
            raise CorpusError(f"{where} is missing: {', '.join(missing)}.")
        if not all(isinstance(entry[key], str) and entry[key].strip() for key in ("doc_id", "title", "path", "source_type", "licence")):
            raise CorpusError(f"{where}: doc_id, title, path, source_type and licence must be non-empty text.")
        if not isinstance(entry["approved_for_medical_use"], bool):
            raise CorpusError(f"{where}: approved_for_medical_use must be true or false.")
        doc_id = entry["doc_id"]
        if not DOC_ID.match(doc_id):
            raise CorpusError(f"{where}: doc_id must be lower-case letters, digits and hyphens.")
        if doc_id in seen:
            raise CorpusError(f"{where}: doc_id '{doc_id}' appears twice.")
        seen.add(doc_id)
        if entry["source_type"] not in ALLOWED_SOURCE_TYPES:
            raise CorpusError(f"{where}: source_type must be one of {list(ALLOWED_SOURCE_TYPES)}.")
        if entry["source_type"] == "approved_reference" and not entry.get("approved_by"):
            raise CorpusError(f"{where}: an approved_reference needs an 'approved_by' record.")
        path = (manifest_path.resolve().parent / entry["path"]).resolve()
        try:
            path.relative_to(base)
        except ValueError as exc:
            raise CorpusError(f"{where}: the path points outside the project folder.") from exc
        if path.suffix.lower() != ".md" or not path.is_file():
            raise CorpusError(f"{where}: the path must be an existing .md file.")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise CorpusError(f"{where}: the file is larger than {MAX_FILE_BYTES} bytes.")
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CorpusError(f"{where}: the file is not UTF-8 text.") from exc
        pieces = split_markdown(text)
        if not pieces:
            raise CorpusError(f"{where}: no passages could be extracted.")
        for number, (section, first, last, body) in enumerate(pieces, start=1):
            passages.append(Passage(doc_id, entry["title"].strip(), section or entry["title"].strip(), f"{doc_id}:{number:03d}", first, last, body))
        documents.append(DocumentInfo(doc_id, entry["title"].strip(), entry["path"], entry["source_type"], entry["licence"].strip(),
                                      entry["approved_for_medical_use"], hashlib.sha256(raw).hexdigest(), len(pieces)))
    return Corpus(tuple(documents), tuple(passages))
