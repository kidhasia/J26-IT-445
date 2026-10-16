"""Upload validation: size, declared MIME type, real file signature, and readability."""

import warnings
from dataclasses import dataclass
from io import BytesIO

from PIL import Image
from pypdf import PdfReader

from lumi.config import Settings
from lumi.errors import LumiError
from lumi.schemas import ErrorCode, InputType

ALLOWED_MIME_TYPES: dict[InputType, frozenset[str]] = {
    InputType.SKIN_IMAGE: frozenset({"image/jpeg", "image/png"}),
    InputType.CHEST_XRAY: frozenset({"image/jpeg", "image/png"}),
    InputType.LAB_REPORT: frozenset({"application/pdf", "image/jpeg", "image/png"}),
}


@dataclass(frozen=True)
class ValidatedFile:
    data: bytes
    mime_type: str
    filename: str | None


def sniff_mime_type(data: bytes) -> str | None:
    """Detect the real file type from its first bytes ("magic numbers"), ignoring what the client claims."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def validate_upload(
    input_type: InputType,
    data: bytes,
    declared_mime: str | None,
    filename: str | None,
    settings: Settings,
) -> ValidatedFile:
    if len(data) == 0:
        raise LumiError(400, ErrorCode.EMPTY_FILE, "The uploaded file is empty.", field="file")
    if len(data) > settings.max_upload_bytes:
        raise LumiError(
            413,
            ErrorCode.FILE_TOO_LARGE,
            f"The uploaded file exceeds the {settings.max_upload_bytes} byte limit.",
            field="file",
        )

    allowed = ALLOWED_MIME_TYPES[input_type]
    allowed_text = ", ".join(sorted(allowed))
    declared = (declared_mime or "").split(";")[0].strip().lower()
    if declared not in allowed:
        raise LumiError(
            415,
            ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            f"Content type '{declared or 'missing'}' is not allowed for input_type "
            f"'{input_type.value}'. Allowed: {allowed_text}.",
            field="file",
        )

    actual = sniff_mime_type(data)
    if actual not in allowed:
        raise LumiError(
            415,
            ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            f"File contents are not a supported format for input_type '{input_type.value}'. "
            f"Allowed: {allowed_text}.",
            field="file",
        )
    if actual != declared:
        raise LumiError(
            415,
            ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            f"Declared content type '{declared}' does not match the file contents ('{actual}').",
            field="file",
        )

    if actual == "application/pdf":
        _check_pdf_readable(data, settings)
    else:
        _check_image_readable(data, settings)

    return ValidatedFile(data=data, mime_type=actual, filename=filename)


def _too_many_pixels(settings: Settings) -> LumiError:
    return LumiError(
        413, ErrorCode.FILE_TOO_LARGE, f"The image exceeds the {settings.max_image_pixels} pixel limit.", field="file"
    )


def _unreadable_image() -> LumiError:
    return LumiError(400, ErrorCode.UNREADABLE_FILE, "The image could not be decoded (corrupt or truncated).", field="file")


def _check_image_readable(data: bytes, settings: Settings) -> None:
    # Step 1: read only the header, so huge images are rejected before decoding them.
    # Pillow raises many different exception types for malformed input; any of them means "unreadable".
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as img:
                pixel_count = img.width * img.height
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise _too_many_pixels(settings) from exc
    except Exception as exc:  # noqa: BLE001
        raise _unreadable_image() from exc
    if pixel_count > settings.max_image_pixels:
        raise _too_many_pixels(settings)

    # Step 2: verify() checks structure; load() fully decodes and catches truncated files verify() misses.
    try:
        with Image.open(BytesIO(data)) as img:
            img.verify()
        with Image.open(BytesIO(data)) as img:
            img.load()
    except Exception as exc:  # noqa: BLE001
        raise _unreadable_image() from exc


def _check_pdf_readable(data: bytes, settings: Settings) -> None:
    try:
        reader = PdfReader(BytesIO(data))
        encrypted = reader.is_encrypted
        page_count = 0 if encrypted else len(reader.pages)
    # pypdf can raise many exception types for malformed input; any of them means "unreadable".
    except Exception as exc:  # noqa: BLE001
        raise LumiError(
            400, ErrorCode.UNREADABLE_FILE, "The PDF could not be read (corrupt or truncated).", field="file"
        ) from exc
    if encrypted:
        raise LumiError(400, ErrorCode.UNREADABLE_FILE, "Password-protected PDFs are not supported.", field="file")
    if page_count == 0:
        raise LumiError(400, ErrorCode.UNREADABLE_FILE, "The PDF has no pages.", field="file")
    if page_count > settings.max_pdf_pages:
        raise LumiError(
            413,
            ErrorCode.FILE_TOO_LARGE,
            f"The PDF has {page_count} pages; the limit is {settings.max_pdf_pages}.",
            field="file",
        )
