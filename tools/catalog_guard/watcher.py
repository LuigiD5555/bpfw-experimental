"""Catalog watcher with automatic relock."""

import time
from pathlib import Path

from bpfw.catalog.catalog_paths import get_catalog_directory
from bpfw.catalog.file_permissions import lock_catalog_files
from bpfw.catalog.state_file import read_state_file, write_state_file

_POLL_INTERVAL_SECONDS = 1


def _collect_catalog_mtimes(catalog_dir: Path) -> dict[Path, float]:
    return {
        path: path.stat().st_mtime
        for path in sorted(catalog_dir.glob("*.yaml"))
        if path.is_file()
    }


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
        catalog_dir = get_catalog_directory()
        yaml_files = sorted(catalog_dir.glob("*.yaml"))
        lock_catalog_files(yaml_files)
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
        catalog_dir = get_catalog_directory()
    except Exception as catalog_error:
        _relock_with_transition("error", str(catalog_error))
        return "relocked_after_error"

    try:
        baseline_mtimes = _collect_catalog_mtimes(catalog_dir)
    except Exception as snapshot_error:
        _relock_with_transition("error", str(snapshot_error))
        return "relocked_after_error"

    try:
        current_state = read_state_file()
        write_state_file(
            {**current_state, "watcher_active": True, "last_event": None, "last_error": None}
        )
    except Exception as state_error:
        _relock_with_transition("error", str(state_error))
        return "relocked_after_error"

    deadline = time.monotonic() + timeout_seconds

    try:
        while time.monotonic() < deadline:
            time.sleep(_POLL_INTERVAL_SECONDS)
            try:
                current_mtimes = _collect_catalog_mtimes(catalog_dir)
            except Exception as poll_error:
                _relock_with_transition("error", str(poll_error))
                return "relocked_after_error"
            if current_mtimes != baseline_mtimes:
                _relock_with_transition("change", None)
                return "relocked_on_change"

        _relock_with_transition("timeout", None)
        return "relocked_on_timeout"
    except Exception as unexpected_error:
        _relock_with_transition("error", str(unexpected_error))
        return "relocked_after_error"
