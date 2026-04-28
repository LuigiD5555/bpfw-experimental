"""Approval signing helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

from bpfw.security.keyring import resolve_hmac_key

APPROVAL_KEY_ENV_VAR = "BPFW_APPROVAL_HMAC_KEY"
_MANIFEST_FALLBACK_KEY_ENV_VAR = "BPFW_MANIFEST_HMAC_KEY"


class ApprovalSigningError(RuntimeError):
    """Raised when approval signature operations fail."""


def load_approval_hmac_key() -> bytes:
    """Load HMAC key for approvals, falling back to manifest key."""

    primary_key = os.getenv(APPROVAL_KEY_ENV_VAR, "").strip()
    fallback_key = os.getenv(_MANIFEST_FALLBACK_KEY_ENV_VAR, "").strip()
    active_key = primary_key or fallback_key
    if not active_key:
        active_key = resolve_hmac_key(
            project_root=Path.cwd(),
            purpose="approval",
            env_var_names=[APPROVAL_KEY_ENV_VAR, _MANIFEST_FALLBACK_KEY_ENV_VAR],
        )
    if not active_key:
        raise ApprovalSigningError(
            "Approval signing key is missing. Set BPFW_APPROVAL_HMAC_KEY or BPFW_MANIFEST_HMAC_KEY. "
            "Example: export BPFW_APPROVAL_HMAC_KEY=\"$(python -c 'import secrets; print(secrets.token_hex(32))')\""
        )
    return active_key.encode("utf-8")


def _canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_approval_payload(payload: dict[str, Any], key: bytes | None = None) -> str:
    """Sign approval payload with HMAC-SHA256."""

    signing_key = key or load_approval_hmac_key()
    return hmac.new(signing_key, _canonical_payload_bytes(payload), hashlib.sha256).hexdigest()


def verify_approval_signature(payload: dict[str, Any], signature: str, key: bytes | None = None) -> bool:
    """Verify approval payload signature."""

    expected_signature = sign_approval_payload(payload=payload, key=key)
    return hmac.compare_digest(expected_signature, signature)
