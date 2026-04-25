"""Password-based unlock key derivation using PBKDF2."""

import hashlib
import sys
import json
from pathlib import Path


def derive_unlock_key(password: str, salt: str = "bpfw-catalog-lock") -> str:
    """Derive a 32-char unlock key from password using PBKDF2.

    Args:
        password: User's sudo/admin password
        salt: Fixed salt for consistency

    Returns:
        32-character hex string (first 32 chars of PBKDF2 output)
    """
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations=100_000,
    )
    return key.hex()[:32]


def store_unlock_key(password: str, key_path: Path) -> None:
    """Store the derived unlock key in a JSON file.

    Args:
        password: User's sudo/admin password
        key_path: Path to .unlock_key file
    """
    # Skip on Windows (admin mode is the authentication)
    if sys.platform == "win32":
        return
    
    key = derive_unlock_key(password)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(json.dumps({"key": key}, indent=2), encoding="utf-8")


def verify_unlock_key(password: str, key_path: Path) -> bool:
    """Verify password against stored unlock key.

    Args:
        password: User's sudo/admin password
        key_path: Path to .unlock_key file

    Returns:
        True if password matches stored key, False otherwise
    """
    if not key_path.exists():
        return True

    try:
        stored = json.loads(key_path.read_text(encoding="utf-8"))
        stored_key = stored.get("key", "")
        derived_key = derive_unlock_key(password)
        return derived_key == stored_key
    except Exception:
        return False
