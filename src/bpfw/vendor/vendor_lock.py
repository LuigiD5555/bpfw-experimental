"""Vendor lock mechanism for immutable blueprint-framework vendoring.

Protects vendor/blueprint-framework from unauthorized modifications.
Requires password to unlock for updates.
"""

import os
import json
from pathlib import Path

from bpfw.catalog.signature import _get_signing_key, _compute_hmac, _verify_hmac


def get_vendor_lock_dir(repo_root: Path) -> Path:
    """Get vendor lock control directory."""
    return repo_root / ".vendor_lock"


def get_vendor_lock_file(repo_root: Path) -> Path:
    """Get vendor lock state file."""
    return get_vendor_lock_dir(repo_root) / "vendor_lock.json"


def get_vendor_unlock_key_file(repo_root: Path) -> Path:
    """Get vendor unlock key file."""
    return get_vendor_lock_dir(repo_root) / ".vendor_unlock_key"


def read_vendor_lock_state(repo_root: Path) -> dict:
    """Read vendor lock state.

    Returns:
        Dict with keys: status, unlocked_at, last_error

    Raises:
        RuntimeError: If lock file doesn't exist or is invalid
    """
    lock_file = get_vendor_lock_file(repo_root)
    if not lock_file.exists():
        raise RuntimeError("Vendor lock not initialized. Run 'bpfw vendor-lock' first.")

    try:
        state = json.loads(lock_file.read_text(encoding="utf-8"))
        return state
    except Exception as e:
        raise RuntimeError(f"Cannot read vendor lock state: {e}")


def write_vendor_lock_state(repo_root: Path, state: dict) -> None:
    """Write vendor lock state atomically."""
    lock_file = get_vendor_lock_file(repo_root)
    lock_dir = lock_file.parent

    lock_dir.mkdir(parents=True, exist_ok=True)

    temp_file = lock_file.with_suffix(".tmp")
    try:
        temp_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temp_file.replace(lock_file)
    except Exception as e:
        raise RuntimeError(f"Cannot write vendor lock state: {e}") from e


def is_vendor_locked(repo_root: Path) -> bool:
    """Check if vendor is locked (based on state file only, not filesystem).

    Returns:
        True if vendor is locked, False if unlocked or lock not initialized
    """
    try:
        state = read_vendor_lock_state(repo_root)
        return state.get("status") == "locked"
    except Exception:
        return False


def _apply_vendor_lock_permissions(repo_root: Path) -> None:
    """Apply read-only permissions to vendor directory recursively.

    First tries chmod, then falls back to git assume-unchanged for NTFS.
    """
    import subprocess

    vendor_dir = repo_root / "vendor"
    if not vendor_dir.exists():
        return

    try:
        for root, dirs, files in os.walk(vendor_dir):
            for file_name in files:
                file_path = Path(root) / file_name
                try:
                    os.chmod(file_path, 0o444)
                except OSError:
                    pass

            for dir_name in dirs:
                dir_path = Path(root) / dir_name
                try:
                    os.chmod(dir_path, 0o555)
                except OSError:
                    pass

        os.chmod(vendor_dir, 0o555)
    except Exception as e:
        print(f"WARN: could not fully lock vendor permissions: {e}")

    try:
        for root, dirs, files in os.walk(vendor_dir):
            for file_name in files:
                file_path = Path(root) / file_name
                try:
                    subprocess.run(
                        ["git", "update-index", "--assume-unchanged", str(file_path)],
                        check=False,
                        capture_output=True,
                    )
                except Exception:
                    pass
    except Exception as e:
        print(f"WARN: could not lock vendor via git: {e}")


def _apply_vendor_unlock_permissions(repo_root: Path) -> None:
    """Apply read-write permissions to vendor directory recursively.

    First removes git assume-unchanged, then tries chmod.
    """
    import subprocess

    vendor_dir = repo_root / "vendor"
    if not vendor_dir.exists():
        return

    try:
        for root, dirs, files in os.walk(vendor_dir):
            for file_name in files:
                file_path = Path(root) / file_name
                try:
                    subprocess.run(
                        ["git", "update-index", "--no-assume-unchanged", str(file_path)],
                        check=False,
                        capture_output=True,
                    )
                except Exception:
                    pass
    except Exception as e:
        print(f"WARN: could not unlock vendor via git: {e}")

    try:
        for root, dirs, files in os.walk(vendor_dir):
            for file_name in files:
                file_path = Path(root) / file_name
                try:
                    os.chmod(file_path, 0o644)
                except OSError:
                    pass

            for dir_name in dirs:
                dir_path = Path(root) / dir_name
                try:
                    os.chmod(dir_path, 0o755)
                except OSError:
                    pass

        os.chmod(vendor_dir, 0o755)
    except Exception as e:
        print(f"WARN: could not fully unlock vendor permissions: {e}")


def lock_vendor_command(password: str, repo_root: Path) -> None:
    """Lock vendor directory.

    Args:
        password: Password to use for locking
        repo_root: Repository root directory

    Raises:
        RuntimeError: If locking fails
    """
    lock_dir = get_vendor_lock_dir(repo_root)
    lock_dir.mkdir(parents=True, exist_ok=True)

    unlock_key_file = get_vendor_unlock_key_file(repo_root)
    lock_file = get_vendor_lock_file(repo_root)

    try:
        from bpfw.catalog.unlock_key import store_unlock_key
        store_unlock_key(password, unlock_key_file)
    except Exception as e:
        raise RuntimeError(f"Cannot store vendor unlock key: {e}")

    state = {
        "status": "locked",
        "unlocked_at": None,
        "last_error": None,
    }

    try:
        write_vendor_lock_state(repo_root, state)

        state_data = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
        key = _get_signing_key(password)
        signature = _compute_hmac(state_data, key)
        state["__signature__"] = signature
        write_vendor_lock_state(repo_root, state)
    except Exception as e:
        raise RuntimeError(f"Cannot sign vendor lock state: {e}")

    try:
        os.chmod(unlock_key_file, 0o600)
        os.chmod(lock_file, 0o444)
        os.chmod(lock_dir, 0o555)
    except Exception as e:
        print(f"WARN: could not protect vendor lock files: {e}")

    _apply_vendor_lock_permissions(repo_root)


def unlock_vendor_command(password: str, repo_root: Path) -> None:
    """Unlock vendor directory.

    Args:
        password: Password to verify
        repo_root: Repository root directory

    Raises:
        RuntimeError: If password is incorrect or unlock fails
    """
    unlock_key_file = get_vendor_unlock_key_file(repo_root)

    if not unlock_key_file.exists():
        raise RuntimeError("Vendor unlock key not found. Run 'bpfw vendor-lock <password>' first.")

    try:
        from bpfw.catalog.unlock_key import verify_unlock_key
        if not verify_unlock_key(password, unlock_key_file):
            raise RuntimeError("Incorrect password for vendor unlock.")
    except Exception as e:
        raise RuntimeError(f"Cannot verify vendor password: {e}")

    lock_file = get_vendor_lock_file(repo_root)
    lock_dir = lock_file.parent

    state = {
        "status": "unlocked",
        "unlocked_at": None,
        "last_error": None,
    }

    try:
        write_vendor_lock_state(repo_root, state)
        os.chmod(lock_dir, 0o755)
        os.chmod(lock_file, 0o644)
        os.chmod(unlock_key_file, 0o600)
    except Exception as e:
        raise RuntimeError(f"Cannot unlock vendor: {e}")

    _apply_vendor_unlock_permissions(repo_root)


def verify_vendor_lock_integrity(password: str, repo_root: Path) -> bool:
    """Verify vendor lock state hasn't been tampered with.

    Args:
        password: Password to derive key from
        repo_root: Repository root directory

    Returns:
        True if signature is valid

    Raises:
        RuntimeError: If verification fails
    """
    lock_file = get_vendor_lock_file(repo_root)

    try:
        state = json.loads(lock_file.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"Cannot read vendor lock state: {e}")

    signature = state.pop("__signature__", None)
    if signature is None:
        return False

    try:
        state_data = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
        key = _get_signing_key(password)
        return _verify_hmac(state_data, signature, key)
    except Exception:
        return False
