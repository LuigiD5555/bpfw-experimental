"""Manifest signature helpers for integrity checks."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

from bpfw.security.keyring import resolve_hmac_key

INTEGRITY_KEY_ENV_VAR = "BPFW_MANIFEST_HMAC_KEY"


class IntegritySigningError(RuntimeError):
    """Raised when a signature operation cannot be executed."""


def load_local_hmac_key(project_root: Path | None = None) -> bytes:
    """Load HMAC key from environment for local development signing."""

    raw_key = os.getenv(INTEGRITY_KEY_ENV_VAR, "").strip()
    if not raw_key and project_root is not None:
        raw_key = resolve_hmac_key(
            project_root=project_root,
            purpose="integrity",
            env_var_names=[INTEGRITY_KEY_ENV_VAR],
        )
    if not raw_key:
        raise IntegritySigningError(
            "Integrity signing key is missing. Set BPFW_MANIFEST_HMAC_KEY. "
            "Example: export BPFW_MANIFEST_HMAC_KEY=\"$(python -c 'import secrets; print(secrets.token_hex(32))')\""
        )
    return raw_key.encode("utf-8")


def _canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_payload(payload: dict[str, Any], key: bytes | None = None, project_root: Path | None = None) -> str:
    """Sign canonical JSON payload with HMAC-SHA256."""

    signing_key = key or load_local_hmac_key(project_root=project_root)
    return hmac.new(signing_key, _canonical_payload_bytes(payload), hashlib.sha256).hexdigest()


def verify_payload_signature(
    payload: dict[str, Any], signature: str, key: bytes | None = None, project_root: Path | None = None
) -> bool:
    """Verify payload signature using local HMAC key."""

    expected_signature = sign_payload(payload=payload, key=key, project_root=project_root)
    return hmac.compare_digest(expected_signature, signature)
