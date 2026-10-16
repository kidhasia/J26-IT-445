"""API-key authentication for client platforms (web, mobile, robot).

Keys come from the LUMI_API_KEYS environment variable as "client_id:key" pairs.
Only SHA-256 hashes of keys are kept in memory, and comparison is constant-time.
This is a prototype scheme; who issues tokens long-term is an open team question (FR8).
"""

import hashlib
import hmac
from collections.abc import Mapping

from lumi.errors import LumiError
from lumi.schemas import ErrorCode

MIN_KEY_LENGTH = 16
_WWW_AUTHENTICATE = {"WWW-Authenticate": "Bearer"}


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def parse_api_keys(raw: str) -> dict[str, str]:
    """Turn 'robot:key1,mobile:key2' into {sha256(key): client_id}."""
    hashes: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        client_id, sep, key = entry.partition(":")
        client_id, key = client_id.strip(), key.strip()
        if not sep or not client_id or len(key) < MIN_KEY_LENGTH:
            raise ValueError(
                f"LUMI_API_KEYS entries must look like 'client_id:key' with keys of at least {MIN_KEY_LENGTH} characters."
            )
        hashes[hash_key(key)] = client_id
    return hashes


class ApiKeyAuthenticator:
    def __init__(self, key_hashes: Mapping[str, str]):
        self._key_hashes = dict(key_hashes)

    def authenticate(self, authorization: str | None) -> str:
        """Return the client_id for a valid 'Authorization: Bearer <key>' header, else raise a 401."""
        scheme, _, token = (authorization or "").partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token:
            raise LumiError(
                401,
                ErrorCode.UNAUTHORIZED,
                "Missing or malformed Authorization header. Expected: 'Authorization: Bearer <api key>'.",
                headers=_WWW_AUTHENTICATE,
            )
        presented = hash_key(token)
        client_id = None
        for stored, candidate in self._key_hashes.items():
            if hmac.compare_digest(stored, presented):
                client_id = candidate
        if client_id is None:
            raise LumiError(401, ErrorCode.UNAUTHORIZED, "Invalid API key.", headers=_WWW_AUTHENTICATE)
        return client_id
