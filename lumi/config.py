"""Central settings for the LUMI API."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from lumi.auth import parse_api_keys

# Placeholder wording. The final text must be approved by the supervisor (see docs/SCOPE_REVIEW.md, FR10).
CLINICAL_BOUNDARY_NOTICE = (
    "LUMI is a research prototype that provides decision support only. "
    "It does not diagnose and does not replace a licensed healthcare professional. "
    "Please discuss any medical concern with a qualified clinician."
)

# Room for multipart boundaries and form fields on top of the file itself.
MULTIPART_OVERHEAD_BYTES = 64 * 1024


@dataclass(frozen=True)
class Settings:
    max_upload_bytes: int = 10 * 1024 * 1024  # 10 MB
    max_question_chars: int = 1000
    max_image_pixels: int = 50_000_000  # protects against "decompression bomb" images
    max_pdf_pages: int = 20
    # {sha256(api key): client_id}. Empty means every /api request is rejected (fail closed).
    api_key_hashes: Mapping[str, str] = field(default_factory=dict)
    rate_limit_per_minute: int = 60

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Settings":
        return cls(
            api_key_hashes=parse_api_keys(env.get("LUMI_API_KEYS", "")),
            rate_limit_per_minute=int(env.get("LUMI_RATE_LIMIT_PER_MINUTE", "60")),
        )
