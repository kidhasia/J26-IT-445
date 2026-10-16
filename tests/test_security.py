"""Authentication, rate limiting, early size rejection and privacy-safe logging."""

import dataclasses
import logging

import pytest
from fastapi.testclient import TestClient

from lumi.auth import ApiKeyAuthenticator, parse_api_keys
from lumi.config import Settings
from lumi.errors import LumiError
from lumi.main import create_app
from lumi.ratelimit import RateLimiter
from lumi.schemas import ErrorCode
from tests.conftest import AUTH_HEADERS, TEST_API_KEY, make_png

URL = "/api/v1/analyze"


def post(client, **kwargs):
    return client.post(
        URL, data={"input_type": "skin_image", **kwargs.pop("data", {})}, files={"file": ("a.png", make_png(), "image/png")}, **kwargs
    )


# ---- API key parsing and checking ----


def test_parse_api_keys_maps_hash_to_client():
    hashes = parse_api_keys(f"robot:{TEST_API_KEY}, mobile:another-key-0123456789")
    assert sorted(hashes.values()) == ["mobile", "robot"]
    assert TEST_API_KEY not in "".join(hashes)  # only hashes are stored


def test_parse_empty_string_gives_no_keys():
    assert parse_api_keys("") == {}


@pytest.mark.parametrize("raw", ["no-colon-here-0123456789", "robot:short", ":missing-client-0123456789"])
def test_parse_api_keys_rejects_bad_entries(raw):
    with pytest.raises(ValueError):
        parse_api_keys(raw)


def test_authenticator_returns_client_id():
    auth = ApiKeyAuthenticator(parse_api_keys(f"robot:{TEST_API_KEY}"))
    assert auth.authenticate(f"Bearer {TEST_API_KEY}") == "robot"
    assert auth.authenticate(f"bearer {TEST_API_KEY}") == "robot"


@pytest.mark.parametrize("header", [None, "", "Bearer", "Basic abc", f"Token {TEST_API_KEY}", "Bearer wrong-key-0123456789"])
def test_authenticator_rejects_bad_headers(header):
    auth = ApiKeyAuthenticator(parse_api_keys(f"robot:{TEST_API_KEY}"))
    with pytest.raises(LumiError) as excinfo:
        auth.authenticate(header)
    assert excinfo.value.status_code == 401
    assert excinfo.value.code == ErrorCode.UNAUTHORIZED


def test_settings_from_env():
    settings = Settings.from_env({"LUMI_API_KEYS": f"web:{TEST_API_KEY}", "LUMI_RATE_LIMIT_PER_MINUTE": "5"})
    assert list(settings.api_key_hashes.values()) == ["web"]
    assert settings.rate_limit_per_minute == 5


# ---- API-level auth ----


def test_health_needs_no_auth(anonymous_client):
    assert anonymous_client.get("/health").status_code == 200


def test_analyze_without_key_is_401(anonymous_client):
    response = post(anonymous_client)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    body = response.json()
    assert body["error"]["code"] == "unauthorized"
    assert body["result"] is None


def test_analyze_with_wrong_key_is_401(anonymous_client):
    response = post(anonymous_client, headers={"Authorization": "Bearer definitely-not-the-key"})
    assert response.status_code == 401


def test_auth_is_checked_before_form_validation(anonymous_client):
    # An unauthenticated caller must not learn anything about the form (no 422 hints).
    response = anonymous_client.post(URL, data={})
    assert response.status_code == 401


def test_no_keys_configured_fails_closed(settings):
    open_settings = dataclasses.replace(settings, api_key_hashes={})
    client = TestClient(create_app(settings=open_settings), headers=AUTH_HEADERS)
    assert post(client).status_code == 401


# ---- rate limiting ----


def test_rate_limiter_blocks_then_recovers_after_window():
    now = [0.0]
    limiter = RateLimiter(max_requests=2, window_seconds=60, clock=lambda: now[0])
    limiter.check("robot")
    limiter.check("robot")
    with pytest.raises(LumiError) as excinfo:
        limiter.check("robot")
    assert excinfo.value.status_code == 429
    assert excinfo.value.headers == {"Retry-After": "60"}
    limiter.check("mobile")  # other clients have their own window
    now[0] = 60.0
    limiter.check("robot")  # window has passed


def test_api_returns_429_with_retry_after(settings):
    limited = dataclasses.replace(settings, rate_limit_per_minute=2)
    client = TestClient(create_app(settings=limited), headers=AUTH_HEADERS)
    assert post(client).status_code == 200
    assert post(client).status_code == 200
    response = post(client)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response.headers["Retry-After"]) >= 1


# ---- early size rejection ----


def test_huge_body_rejected_from_content_length(client):
    huge = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200_000
    response = client.post(URL, data={"input_type": "skin_image"}, files={"file": ("h.png", huge, "image/png")})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


# ---- logging contains no health data ----


def test_logs_do_not_contain_question_filename_or_metadata(client, caplog):
    secret_question = "Is my daughter Nimali's rash dangerous?"
    with caplog.at_level(logging.INFO, logger="lumi"):
        response = client.post(
            URL,
            data={"input_type": "skin_image", "question": secret_question, "metadata": '{"locale": "si-LK"}'},
            files={"file": ("nimali_rash_2026.png", make_png(), "image/png")},
        )
    assert response.status_code == 200
    logs = caplog.text
    assert response.json()["request_id"] in logs
    assert '"has_question": true' in logs
    for forbidden in ["Nimali", "rash", "nimali_rash_2026", "si-LK", TEST_API_KEY]:
        assert forbidden not in logs


def test_error_requests_are_logged_with_code(client, caplog):
    with caplog.at_level(logging.INFO, logger="lumi"):
        client.post(URL, data={"input_type": "skin_image"}, files={"file": ("e.png", b"", "image/png")})
    assert '"error_code": "empty_file"' in caplog.text
