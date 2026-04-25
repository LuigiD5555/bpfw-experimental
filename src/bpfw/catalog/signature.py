"""Digital signature for catalog integrity files.

Uses HMAC-SHA256 to sign and verify:
- hashes.lock (catalog file hashes)
- lockstate.json (lock state)

Ensures these files cannot be forged without the signing key.
"""

import hashlib
import hmac
import json
from pathlib import Path

from bpfw.catalog.unlock_key import derive_unlock_key


def _get_signing_key(password: str) -> bytes:
    """Derive HMAC signing key from password using PBKDF2.

    Args:
        password: User's password (same as unlock password)

    Returns:
        32-byte HMAC key
    """
    derived = derive_unlock_key(password, salt="bpfw-catalog-sign")
    return bytes.fromhex(derived)


def _compute_hmac(data: bytes, key: bytes) -> str:
    """Compute HMAC-SHA256 signature.

    Args:
        data: Data to sign
        key: HMAC key

    Returns:
        Hex string of HMAC
    """
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def _verify_hmac(data: bytes, signature: str, key: bytes) -> bool:
    """Verify HMAC-SHA256 signature.

    Args:
        data: Data that was signed
        signature: HMAC hex string
        key: HMAC key

    Returns:
        True if signature matches
    """
    expected = _compute_hmac(data, key)
    return hmac.compare_digest(expected, signature)


def sign_hashes_lock(hashes_path: Path, password: str) -> None:
    """Sign hashes.lock file with HMAC.

    Appends a signature field to the JSON.

    Args:
        hashes_path: Path to hashes.lock
        password: User's password for key derivation
    """
    hashes = json.loads(hashes_path.read_text(encoding="utf-8"))
    hashes.pop("__signature__", None)

    data = json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    key = _get_signing_key(password)
    signature = _compute_hmac(data, key)

    hashes["__signature__"] = signature
    hashes_path.write_text(json.dumps(hashes, indent=2), encoding="utf-8")


def verify_hashes_lock(hashes_path: Path, password: str) -> bool:
    """Verify hashes.lock signature.

    Args:
        hashes_path: Path to hashes.lock
        password: User's password for key derivation

    Returns:
        True if signature is valid

    Raises:
        ValueError: If signature is missing or invalid format
    """
    if not hashes_path.exists():
        return True

    try:
        hashes = json.loads(hashes_path.read_text(encoding="utf-8"))
    except Exception:
        return False

    signature = hashes.pop("__signature__", None)
    if signature is None:
        return False

    try:
        data = json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
        key = _get_signing_key(password)
        return _verify_hmac(data, signature, key)
    except Exception:
        return False


def sign_lockstate(lockstate_path: Path, password: str) -> None:
    """Sign lockstate.json file with HMAC.

    Appends a signature field to the JSON.

    Args:
        lockstate_path: Path to lockstate.json
        password: User's password for key derivation
    """
    state = json.loads(lockstate_path.read_text(encoding="utf-8"))
    state.pop("__signature__", None)

    data = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    key = _get_signing_key(password)
    signature = _compute_hmac(data, key)

    state["__signature__"] = signature
    lockstate_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def verify_lockstate(lockstate_path: Path, password: str) -> bool:
    """Verify lockstate.json signature.

    Args:
        lockstate_path: Path to lockstate.json
        password: User's password for key derivation

    Returns:
        True if signature is valid
    """
    if not lockstate_path.exists():
        return True

    try:
        state = json.loads(lockstate_path.read_text(encoding="utf-8"))
    except Exception:
        return False

    signature = state.pop("__signature__", None)
    if signature is None:
        return False

    try:
        data = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
        key = _get_signing_key(password)
        return _verify_hmac(data, signature, key)
    except Exception:
        return False
