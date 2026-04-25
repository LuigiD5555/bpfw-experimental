"""Catalog authority operations extracted into BPFW."""

import argparse
import datetime
import os
import subprocess
import sys
import time
from pathlib import Path

from bpfw.catalog.catalog_paths import (
    CatalogDirectoryNotFoundError,
    CatalogFilesNotFoundError,
    get_catalog_directory,
    get_repo_root,
    list_catalog_yaml_files,
)
from bpfw.catalog.file_permissions import select_strategy
from bpfw.catalog.catalog_hashes import compute_catalog_hashes, write_hashes_file
from bpfw.catalog.state_file import read_state_file, write_state_file
from bpfw.catalog.unlock_key import store_unlock_key, verify_unlock_key
from bpfw.catalog.signature import sign_hashes_lock, sign_lockstate, verify_hashes_lock, verify_lockstate

_POLL_INTERVAL_SECONDS = 1.0
_DEFAULT_TIMEOUT_SECONDS = 300


def _now_iso() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


def is_locked_real() -> bool:
    try:
        yaml_files = list_catalog_yaml_files()
        if not yaml_files:
            return True
        strategy = select_strategy(yaml_files)
        return strategy.is_locked()
    except Exception:
        return True


def lock_catalog_command() -> int:
    try:
        yaml_files = list_catalog_yaml_files()
    except (CatalogDirectoryNotFoundError, CatalogFilesNotFoundError) as error:
        print(f"ERROR: {error}")
        return 1

    strategy = select_strategy(yaml_files)
    strategy.require_elevation()

    try:
        strategy.lock()
    except Exception as error:
        print(f"ERROR: failed to lock catalog: {error}")
        return 1

    user_password = None
    try:
        repo_root = get_repo_root()
        hashes = compute_catalog_hashes(yaml_files)
        hashes_path = repo_root / "src" / ".catalog" / "hashes.lock"
        write_hashes_file(hashes_path, hashes)

        if sys.platform != "win32":
            print("\n🔒 Configura tu contraseña de desbloqueo:")
            user_password = input("Password: ").strip()
            unlock_key_path = repo_root / "src" / ".catalog" / ".unlock_key"
            store_unlock_key(user_password, unlock_key_path)
            sign_hashes_lock(hashes_path, user_password)
    except Exception as error:
        print(f"WARN: could not save catalog hashes: {error}")

    lock_state = {
        "status": "locked",
        "opened_at": None,
        "watcher_active": False,
        "last_event": None,
        "last_error": None,
    }
    write_state_file(lock_state)

    if user_password and sys.platform != "win32":
        try:
            repo_root = get_repo_root()
            lockstate_path = repo_root / ".catalog" / "lockstate.json"
            sign_lockstate(lockstate_path, user_password)
        except Exception as e:
            print(f"WARN: could not sign lockstate: {e}")
    # Protect .catalog directory itself
    try:
        catalog_control_dir = repo_root / "src" / ".catalog"
        catalog_control_dir.mkdir(parents=True, exist_ok=True)
        for item in catalog_control_dir.iterdir():
            if item.is_file():
                os.chmod(item, 0o444)
        os.chmod(catalog_control_dir, 0o555)
        print("✅ Protected .catalog directory")
    except Exception as e:
        print(f"WARN: could not protect .catalog directory: {e}")

    strategy_name = strategy.get_strategy_name()
    print(f"SUCCESS: catalog locked ({strategy_name})")
    return 0
def _start_idle_autolock_daemon() -> None:
    idle_seconds = int(os.environ.get("CATALOG_IDLE_AUTOLOCK_SECONDS", "30"))
    daemon_command = [
        sys.executable,
        "-m",
        "bpfw.catalog.authority",
        "idle-autolock",
        "--idle-seconds",
        str(idle_seconds),
    ]
    try:
        subprocess.Popen(
            daemon_command,
            cwd=str(get_repo_root()),
            env=os.environ.copy(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        print(f"INFO: idle autolock daemon started ({idle_seconds}s timeout)")
    except Exception as error:
        print(f"WARN: could not start idle autolock daemon: {error}")


def unlock_catalog_command(require_sudo: bool = True) -> int:
    try:
        yaml_files = list_catalog_yaml_files()
    except (CatalogDirectoryNotFoundError, CatalogFilesNotFoundError) as error:
        print(f"ERROR: {error}")
        return 1

    strategy = select_strategy(yaml_files)

    if require_sudo:
        strategy.require_elevation()

    repo_root = get_repo_root()
    unlock_key_path = repo_root / "src" / ".catalog" / ".unlock_key"

    if unlock_key_path.exists() and sys.platform != "win32":
        print("\n🔓 Verifica tu contraseña para desbloquear:")
        user_password = input("Password: ").strip()

        if not verify_unlock_key(user_password, unlock_key_path):
            print("\n❌ Contraseña incorrecta. Desbloqueo rechazado.")
            return 1
        print("✅ Contraseña verificada.")

    try:
        strategy.unlock()
    except Exception as error:
        print(f"ERROR: failed to unlock catalog: {error}")
        return 1

    write_state_file(
        {
            "status": "unlocked",
            "opened_at": _now_iso(),
            "watcher_active": False,
            "last_event": None,
            "last_error": None,
        }
    )
    # Restore .catalog directory permissions
    try:
        catalog_control_dir = repo_root / "src" / ".catalog"
        os.chmod(catalog_control_dir, 0o755)
        for item in catalog_control_dir.iterdir():
            if item.is_file():
                if item.name == ".unlock_key":
                    os.chmod(item, 0o600)
                elif item.name == "hashes.lock":
                    os.chmod(item, 0o444)
                else:
                    os.chmod(item, 0o644)
        print("✅ Restored .catalog directory permissions")
    except Exception as e:
        print(f"WARN: could not restore .catalog permissions: {e}")

    strategy_name = strategy.get_strategy_name()
    print(f"SUCCESS: catalog unlocked ({strategy_name})")
    _start_idle_autolock_daemon()
    return 0


def _collect_latest_mtime(catalog_directory_path: Path) -> float:
    latest_mtime = 0.0
    for yaml_path in sorted(catalog_directory_path.glob("*.yaml")):
        if yaml_path.is_file():
            latest_mtime = max(latest_mtime, yaml_path.stat().st_mtime)
    return latest_mtime


def run_idle_autolock(idle_seconds: int) -> int:
    catalog_directory_path = get_catalog_directory()
    latest_mtime = _collect_latest_mtime(catalog_directory_path)
    last_activity_monotonic = time.monotonic()
    while True:
        try:
            state = read_state_file()
        except Exception:
            return 1
        if state.get("status") != "unlocked":
            return 0
        current_latest_mtime = _collect_latest_mtime(catalog_directory_path)
        if current_latest_mtime != latest_mtime:
            latest_mtime = current_latest_mtime
            last_activity_monotonic = time.monotonic()
        if (time.monotonic() - last_activity_monotonic) >= float(idle_seconds):
            return lock_catalog_command()
        time.sleep(_POLL_INTERVAL_SECONDS)


def _relock_with_transition(last_event: str, last_error: str | None = None) -> None:
    try:
        write_state_file(
            {
                "status": "relocking",
                "opened_at": None,
                "watcher_active": False,
                "last_event": last_event,
                "last_error": last_error,
            }
        )
    except Exception:
        pass
    try:
        yaml_files = sorted(get_catalog_directory().glob("*.yaml"))
        strategy = select_strategy(yaml_files)
        strategy.lock()
        hashes = compute_catalog_hashes(yaml_files)
        repo_root = get_repo_root()
        hashes_path = repo_root / "src" / ".catalog" / "hashes.lock"
        write_hashes_file(hashes_path, hashes)
    except Exception:
        pass
    write_state_file(
        {
            "status": "locked",
            "opened_at": None,
            "watcher_active": False,
            "last_event": last_event,
            "last_error": last_error,
        }
    )


def watch_catalog_changes(timeout_seconds: int) -> str:
    try:
        catalog_directory = get_catalog_directory()
        baseline_latest_mtime = _collect_latest_mtime(catalog_directory)
    except Exception as error:
        _relock_with_transition("error", str(error))
        return "relocked_after_error"

    try:
        current_state = read_state_file()
        write_state_file({**current_state, "watcher_active": True, "last_event": None, "last_error": None})
    except Exception as error:
        _relock_with_transition("error", str(error))
        return "relocked_after_error"

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        time.sleep(_POLL_INTERVAL_SECONDS)
        try:
            current_latest_mtime = _collect_latest_mtime(catalog_directory)
        except Exception as error:
            _relock_with_transition("error", str(error))
            return "relocked_after_error"
        if current_latest_mtime != baseline_latest_mtime:
            _relock_with_transition("change", None)
            return "relocked_on_change"
    _relock_with_transition("timeout", None)
    return "relocked_on_timeout"


def open_catalog_session() -> None:
    current_state = read_state_file()
    if current_state["status"] == "unlocked":
        raise RuntimeError("A catalog edit session is already open.")
    result = unlock_catalog_command(require_sudo=False)
    if result != 0:
        raise RuntimeError("Cannot open catalog session.")


def close_catalog_session() -> None:
    result = lock_catalog_command()
    if result != 0:
        raise RuntimeError("Cannot close catalog session.")


def run_guard() -> int:
    try:
        open_catalog_session()
    except Exception as error:
        print(f"[run_guard] session open failed: {error}", file=sys.stderr)
        return 1
    try:
        watch_catalog_changes(_DEFAULT_TIMEOUT_SECONDS)
    finally:
        try:
            close_catalog_session()
        except Exception as error:
            print(f"[run_guard] relock failed in finally: {error}", file=sys.stderr)
    try:
        final_state = read_state_file()
    except Exception as error:
        print(f"[run_guard] cannot read final state: {error}", file=sys.stderr)
        return 1
    if final_state.get("status") != "locked":
        print(f"[run_guard] inconsistency: expected status='locked', got {final_state.get('status')!r}", file=sys.stderr)
        return 1
    return 0


def install_hooks_command(force: bool = False) -> int:
    """Install pre-commit hook for catalog immutability enforcement.

    The hook is sourced from src/bpfw/hooks/pre-commit (bundled with bpfw).
    It enforces that no changes to src/catalog/**/*.yaml are permitted when
    the catalog is locked (detected via .catalog/lockstate.json).

    Args:
        force: If True, overwrite existing hook. If False, fail if hook exists.

    Returns:
        0 on success, 1 on error.
    """
    try:
        repo_root = get_repo_root()
    except Exception as error:
        print(f"ERROR: Could not determine repository root: {error}")
        return 1

    git_hooks_dir = repo_root / ".git" / "hooks"
    target_hook = git_hooks_dir / "pre-commit"

    # Load hook template from package
    hook_template_path = Path(__file__).parent.parent / "hooks" / "pre-commit"
    if not hook_template_path.exists():
        print(f"ERROR: Hook template not found at {hook_template_path}")
        return 1

    try:
        hook_content = hook_template_path.read_text(encoding="utf-8")
    except Exception as error:
        print(f"ERROR: Could not read hook template: {error}")
        return 1

    # Check if hook already exists
    if target_hook.exists() and not force:
        print(f"ERROR: Hook already exists at {target_hook}")
        print("Use --force to overwrite.")
        return 1

    # Ensure .git/hooks directory exists
    try:
        git_hooks_dir.mkdir(parents=True, exist_ok=True)
    except Exception as error:
        print(f"ERROR: Could not create .git/hooks directory: {error}")
        return 1

    # Write hook to target location
    try:
        target_hook.write_text(hook_content, encoding="utf-8")
    except Exception as error:
        print(f"ERROR: Could not write hook to {target_hook}: {error}")
        return 1

    # Make hook executable
    try:
        current_mode = target_hook.stat().st_mode
        executable_mode = current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        target_hook.chmod(executable_mode)
    except Exception as error:
        print(f"ERROR: Could not make hook executable: {error}")
        return 1

    print(f"SUCCESS: Pre-commit hook installed at {target_hook}")
    print("The hook will enforce catalog immutability when locked via 'bpfw lock'.")
    return 0




def authority_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AIOA authority commands.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("lock")
    subparsers.add_parser("unlock")
    idle_parser = subparsers.add_parser("idle-autolock")
    idle_parser.add_argument("--idle-seconds", type=int, default=30)
    subparsers.add_parser("run-guard")
    arguments = parser.parse_args(argv)

    if arguments.command == "lock":
        return lock_catalog_command()
    if arguments.command == "unlock":
        return unlock_catalog_command(require_sudo=True)
    if arguments.command == "idle-autolock":
        return run_idle_autolock(arguments.idle_seconds)
    if arguments.command == "run-guard":
        return run_guard()
    return 1


if __name__ == "__main__":
    raise SystemExit(authority_cli())

