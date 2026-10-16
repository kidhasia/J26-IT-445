import pytest

from lumi.errors import LumiError
from lumi.schemas import ErrorCode, InputType
from lumi.validation import sniff_mime_type, validate_upload
from tests.conftest import TEST_MAX_UPLOAD_BYTES, make_jpeg, make_pdf, make_png


def assert_rejected(excinfo, status: int, code: ErrorCode) -> None:
    assert excinfo.value.status_code == status
    assert excinfo.value.code == code


def test_sniff_detects_png_jpeg_pdf_and_unknown():
    assert sniff_mime_type(make_png()) == "image/png"
    assert sniff_mime_type(make_jpeg()) == "image/jpeg"
    assert sniff_mime_type(make_pdf()) == "application/pdf"
    assert sniff_mime_type(b"hello world") is None


@pytest.mark.parametrize(
    "input_type, data, mime",
    [
        (InputType.SKIN_IMAGE, make_png(), "image/png"),
        (InputType.SKIN_IMAGE, make_jpeg(), "image/jpeg"),
        (InputType.CHEST_XRAY, make_png(), "image/png"),
        (InputType.LAB_REPORT, make_pdf(), "application/pdf"),
        (InputType.LAB_REPORT, make_jpeg(), "image/jpeg"),
    ],
)
def test_valid_files_are_accepted(settings, input_type, data, mime):
    validated = validate_upload(input_type, data, mime, "x", settings)
    assert validated.mime_type == mime
    assert validated.data == data


def test_declared_mime_parameters_are_ignored(settings):
    validated = validate_upload(InputType.SKIN_IMAGE, make_png(), "image/png; charset=binary", "x", settings)
    assert validated.mime_type == "image/png"


def test_empty_file_rejected(settings):
    with pytest.raises(LumiError) as excinfo:
        validate_upload(InputType.SKIN_IMAGE, b"", "image/png", "x", settings)
    assert_rejected(excinfo, 400, ErrorCode.EMPTY_FILE)


def test_oversized_file_rejected(settings):
    data = make_png() + b"\x00" * TEST_MAX_UPLOAD_BYTES
    with pytest.raises(LumiError) as excinfo:
        validate_upload(InputType.SKIN_IMAGE, data, "image/png", "x", settings)
    assert_rejected(excinfo, 413, ErrorCode.FILE_TOO_LARGE)


def test_disallowed_declared_type_rejected(settings):
    with pytest.raises(LumiError) as excinfo:
        validate_upload(InputType.SKIN_IMAGE, b"just text", "text/plain", "x", settings)
    assert_rejected(excinfo, 415, ErrorCode.UNSUPPORTED_MEDIA_TYPE)


def test_pdf_not_allowed_for_skin_image(settings):
    with pytest.raises(LumiError) as excinfo:
        validate_upload(InputType.SKIN_IMAGE, make_pdf(), "application/pdf", "x", settings)
    assert_rejected(excinfo, 415, ErrorCode.UNSUPPORTED_MEDIA_TYPE)


def test_text_disguised_as_png_rejected(settings):
    with pytest.raises(LumiError) as excinfo:
        validate_upload(InputType.SKIN_IMAGE, b"not really an image", "image/png", "x", settings)
    assert_rejected(excinfo, 415, ErrorCode.UNSUPPORTED_MEDIA_TYPE)


def test_declared_type_must_match_contents(settings):
    with pytest.raises(LumiError) as excinfo:
        validate_upload(InputType.SKIN_IMAGE, make_png(), "image/jpeg", "x", settings)
    assert_rejected(excinfo, 415, ErrorCode.UNSUPPORTED_MEDIA_TYPE)


def test_truncated_png_rejected(settings):
    data = make_png((64, 64))
    with pytest.raises(LumiError) as excinfo:
        validate_upload(InputType.SKIN_IMAGE, data[: len(data) // 2], "image/png", "x", settings)
    assert_rejected(excinfo, 400, ErrorCode.UNREADABLE_FILE)


def test_truncated_jpeg_rejected(settings):
    data = make_jpeg((64, 64))
    with pytest.raises(LumiError) as excinfo:
        validate_upload(InputType.CHEST_XRAY, data[: len(data) // 2], "image/jpeg", "x", settings)
    assert_rejected(excinfo, 400, ErrorCode.UNREADABLE_FILE)


def test_image_with_too_many_pixels_rejected(settings):
    data = make_png((1100, 1000))  # 1.1M pixels > 1M test limit, but few bytes
    with pytest.raises(LumiError) as excinfo:
        validate_upload(InputType.SKIN_IMAGE, data, "image/png", "x", settings)
    assert_rejected(excinfo, 413, ErrorCode.FILE_TOO_LARGE)


def test_corrupt_pdf_rejected(settings):
    with pytest.raises(LumiError) as excinfo:
        validate_upload(InputType.LAB_REPORT, b"%PDF-1.4\nthis is not a real pdf", "application/pdf", "x", settings)
    assert_rejected(excinfo, 400, ErrorCode.UNREADABLE_FILE)


def test_pdf_with_too_many_pages_rejected(settings):
    with pytest.raises(LumiError) as excinfo:
        validate_upload(InputType.LAB_REPORT, make_pdf(pages=4), "application/pdf", "x", settings)
    assert_rejected(excinfo, 413, ErrorCode.FILE_TOO_LARGE)
