"""Shared test fixtures. All test files are generated in memory; no real medical data is used."""

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter

from lumi.auth import parse_api_keys
from lumi.config import Settings
from lumi.main import create_app
from lumi.pipelines.mock import MockPipeline
from lumi.pipelines.ocr.engine import TesseractEngine
from lumi.pipelines.ocr.pipeline import LabReportOcrPipeline
from lumi.schemas import InputType
from lumi.service import AnalysisService

TEST_MAX_UPLOAD_BYTES = 50_000


def build_test_service() -> AnalysisService:
    """The service used by tests that are about validation, auth, rate limits or logging.
    Skin uses the explicit placeholder (no prediction), so these tests do not depend on a trained model."""
    return AnalysisService(
        {
            InputType.SKIN_IMAGE: MockPipeline(InputType.SKIN_IMAGE),
            InputType.CHEST_XRAY: MockPipeline(InputType.CHEST_XRAY),
            InputType.LAB_REPORT: LabReportOcrPipeline(TesseractEngine()),
        }
    )
TEST_API_KEY = "test-key-0123456789abcdef"
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_API_KEY}"}


def make_png(size: tuple[int, int] = (32, 32)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color=(200, 120, 90)).save(buf, format="PNG")
    return buf.getvalue()


def make_jpeg(size: tuple[int, int] = (32, 32)) -> bytes:
    buf = BytesIO()
    Image.new("L", size, color=128).save(buf, format="JPEG")
    return buf.getvalue()


def make_pdf(pages: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        max_upload_bytes=TEST_MAX_UPLOAD_BYTES,
        max_image_pixels=1_000_000,
        max_pdf_pages=3,
        api_key_hashes=parse_api_keys(f"test:{TEST_API_KEY}"),
        rate_limit_per_minute=1000,
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    """An authenticated client: every request carries a valid API key."""
    return TestClient(create_app(settings=settings, service=build_test_service()), headers=AUTH_HEADERS)


@pytest.fixture
def anonymous_client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings=settings, service=build_test_service()))
