"""Catalog authority operations extracted into AIOA."""

import argparse
import datetime
import os
import subprocess
import sys
import time
from pathlib import Path

from aioa.catalog.catalog_paths import (
    CatalogDirectoryNotFoundError,
    CatalogFilesNotFoundError,
    get_catalog_directory,
    get_repo_root,
    list_catalog_yaml_files,
)
from aioa.catalog.file_permissions import (
    assert_catalog_state,
    detect_permission_enforcement_support,
    lock_catalog_files,
    unlock_catalog_files,
)
from aioa.catalog.state_file import read_state_file, write_state_file

_POLL_INTERVAL_SECONDS = 1.0
_DEFAULT_TIMEOUT_SECONDS = 300


def _now_iso() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


def lock_catalog_command() -> int:
    try:
        yaml_files = list_catalog_yaml_files()
    except (CatalogDirectoryNotFoundError, CatalogFilesNotFoundError) as error:
        print(f"ERROR: {error}")
        return 1

    chmod_supported = detect_permission_enforcement_support(yaml_files)
    try:
        lock_catalog_files(yaml_files)
        assert_catalog_state(yaml_files, expected_writable=False)
    except (AssertionError, PermissionError) as error:
        print(f"ERROR: {error}")
        return 1

    write_state_file(
        {
            "status": "locked",
            "opened_at": None,
            "watcher_active": False,
            "last_event": None,
            "last_error": None,
        }
    )
    mode = "chmod+state" if chmod_supported else "state-only"
    print(f"SUCCESS: catalog locked ({mode})")
    return 0


def _require_sudo() -> None:
    if os.geteuid() == 0:
        return
    print("This operation requires superuser privileges.")
    print("You will be prompted for your password.\n")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(get_repo_root())
    command = ["sudo", "-p", "[sudo] password for %u: ", sys.executable, __file__, *sys.argv[1:]]
    try:
        result = subprocess.run(command, env=environment, check=False)
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
        raise SystemExit(1) from None
    raise SystemExit(result.returncode)


def _start_idle_autolock_daemon() -> None:
    idle_seconds = int(os.environ.get("CATALOG_IDLE_AUTOLOCK_SECONDS", "30"))
    daemon_command = [
        sys.executable,
        "-m",
        "aioa.catalog.authority",
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
    if require_sudo:
        _require_sudo()

    try:
        yaml_files = list_catalog_yaml_files()
    except (CatalogDirectoryNotFoundError, CatalogFilesNotFoundError) as error:
        print(f"ERROR: {error}")
        return 1

    chmod_supported = detect_permission_enforcement_support(yaml_files)
    try:
        unlock_catalog_files(yaml_files)
        assert_catalog_state(yaml_files, expected_writable=True)
    except (AssertionError, PermissionError) as error:
        print(f"ERROR: {error}")
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
    mode = "chmod+state" if chmod_supported else "state-only"
    print(f"SUCCESS: catalog unlocked ({mode})")
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
        lock_catalog_files(sorted(get_catalog_directory().glob("*.yaml")))
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

