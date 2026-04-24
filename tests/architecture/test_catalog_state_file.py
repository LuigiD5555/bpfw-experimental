"""State-file contract for lock backend persistence."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from bpfw.catalog.state_file import (
    CatalogGuardInvalidStatePayloadError,
    read_state_file,
    write_state_file,
)


def test_write_and_read_locked_state_with_backend(tmp_path: Path) -> None:
    with patch("bpfw.catalog.state_file.get_repo_root", return_value=tmp_path):
        write_state_file(
            {
                "status": "locked",
                "lock_backend": "linux_immutable",
                "opened_at": None,
                "watcher_active": False,
                "last_event": None,
                "last_error": None,
            }
        )
        state = read_state_file()
    assert state["status"] == "locked"
    assert state["lock_backend"] == "linux_immutable"


def test_locked_state_requires_backend(tmp_path: Path) -> None:
    with patch("bpfw.catalog.state_file.get_repo_root", return_value=tmp_path):
        with pytest.raises(CatalogGuardInvalidStatePayloadError, match="locked status requires lock_backend"):
            write_state_file(
                {
                    "status": "locked",
                    "lock_backend": None,
                    "opened_at": None,
                    "watcher_active": False,
                    "last_event": None,
                    "last_error": None,
                }
            )


def test_unlocked_state_must_not_keep_backend(tmp_path: Path) -> None:
    with patch("bpfw.catalog.state_file.get_repo_root", return_value=tmp_path):
        with pytest.raises(CatalogGuardInvalidStatePayloadError, match="lock_backend must be null"):
            write_state_file(
                {
                    "status": "unlocked",
                    "lock_backend": "linux_immutable",
                    "opened_at": None,
                    "watcher_active": False,
                    "last_event": None,
                    "last_error": None,
                }
            )


def test_locked_state_hardens_lockstate_storage(tmp_path: Path) -> None:
    with patch("bpfw.catalog.state_file.get_repo_root", return_value=tmp_path):
        write_state_file(
            {
                "status": "locked",
                "lock_backend": "linux_immutable",
                "opened_at": None,
                "watcher_active": False,
                "last_event": None,
                "last_error": None,
            }
        )
        state_path = tmp_path / ".catalog" / "lockstate.json"
        state_directory = state_path.parent
        assert state_path.exists()
        assert os.access(state_path, os.W_OK) is False
        assert os.access(state_directory, os.W_OK) is False


def test_write_state_file_unlock_reopens_storage_after_locked(tmp_path: Path) -> None:
    with patch("bpfw.catalog.state_file.get_repo_root", return_value=tmp_path):
        write_state_file(
            {
                "status": "locked",
                "lock_backend": "linux_immutable",
                "opened_at": None,
                "watcher_active": False,
                "last_event": None,
                "last_error": None,
            }
        )
        write_state_file(
            {
                "status": "unlocked",
                "lock_backend": None,
                "opened_at": None,
                "watcher_active": False,
                "last_event": None,
                "last_error": None,
            }
        )
        state_path = tmp_path / ".catalog" / "lockstate.json"
        state_directory = state_path.parent
        assert os.access(state_path, os.W_OK) is True
        assert os.access(state_directory, os.W_OK) is True
