"""Manifest signature helpers for integrity checks."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any


INTEGRITY_KEY_ENV_VAR = "BPFW_MANIFEST_HMAC_KEY"


class IntegritySigningError(RuntimeError):
    """Raised when a signature operation cannot be executed."""


def load_local_hmac_key() -> bytes:
    """Load HMAC key from environment for local development signing."""

    raw_key = os.getenv(INTEGRITY_KEY_ENV_VAR, "").strip()
    if not raw_key:
        raise IntegritySigningError(
            "Integrity signing key is missing. Set BPFW_MANIFEST_HMAC_KEY. "
            "Example: export BPFW_MANIFEST_HMAC_KEY=\"$(python -c 'import secrets; print(secrets.token_hex(32))')\""
        )
    return raw_key.encode("utf-8")


def _canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_payload(payload: dict[str, Any], key: bytes | None = None) -> str:
    """Sign canonical JSON payload with HMAC-SHA256."""

    signing_key = key or load_local_hmac_key()
    return hmac.new(signing_key, _canonical_payload_bytes(payload), hashlib.sha256).hexdigest()


def verify_payload_signature(payload: dict[str, Any], signature: str, key: bytes | None = None) -> bool:
    """Verify payload signature using local HMAC key."""

    expected_signature = sign_payload(payload=payload, key=key)
    return hmac.compare_digest(expected_signature, signature)
