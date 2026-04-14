"""Catalog access control: enforce locked state before operations."""

from pathlib import Path
from unittest.mock import patch

import pytest

from bpfw.catalog.access_control import (
    CatalogLockedError,
    CatalogStateCheckError,
    assert_catalog_unlocked,
)
from bpfw.catalog.loader import load_catalog_documents


_LOCKED_STATE = {
    "status": "locked",
    "opened_at": None,
    "watcher_active": False,
    "last_event": None,
    "last_error": None,
}

_UNLOCKED_STATE = {
    "status": "unlocked",
    "opened_at": "2026-04-12T12:00:00+00:00",
    "watcher_active": False,
    "last_event": None,
    "last_error": None,
}


def test_assert_catalog_unlocked_passes_when_unlocked() -> None:
    """When guard state is 'unlocked', assertion passes."""
    with patch("bpfw.catalog.access_control.read_state_file", return_value=_UNLOCKED_STATE):
        assert_catalog_unlocked()  # must not raise


def test_assert_catalog_unlocked_fails_when_locked() -> None:
    """When guard state is 'locked', assertion raises CatalogLockedError."""
    with patch("bpfw.catalog.access_control.read_state_file", return_value=_LOCKED_STATE):
        with pytest.raises(CatalogLockedError, match="Catalog is locked"):
            assert_catalog_unlocked()


def test_assert_catalog_unlocked_passes_when_state_file_missing() -> None:
    """When state file does not exist, treat as unlocked (backward compat)."""
    from bpfw.catalog.state_file import CatalogGuardStateFileNotFoundError

    with patch(
        "bpfw.catalog.access_control.read_state_file",
        side_effect=CatalogGuardStateFileNotFoundError(Path(".catalog/lockstate.json")),
    ):
        assert_catalog_unlocked()  # must not raise


def test_assert_catalog_unlocked_fails_on_state_read_error() -> None:
    """When state file cannot be read/parsed, raise CatalogStateCheckError."""
    with patch(
        "bpfw.catalog.access_control.read_state_file",
        side_effect=ValueError("invalid JSON"),
    ):
        with pytest.raises(CatalogStateCheckError, match="Cannot verify catalog"):
            assert_catalog_unlocked()


def test_load_catalog_documents_fails_when_locked() -> None:
    """load_catalog_documents must fail immediately if catalog is locked."""
    with patch("bpfw.catalog.access_control.read_state_file", return_value=_LOCKED_STATE):
        with pytest.raises(CatalogLockedError, match="Catalog is locked"):
            load_catalog_documents()


def test_load_catalog_documents_succeeds_when_unlocked() -> None:
    """load_catalog_documents succeeds when catalog is unlocked."""
    with (
        patch("bpfw.catalog.access_control.read_state_file", return_value=_UNLOCKED_STATE),
        patch("bpfw.catalog.loader.list_catalog_yaml_files", return_value=[]),
        patch("bpfw.catalog.loader.validate_raw_catalog_documents"),
    ):
        docs = load_catalog_documents()
        assert docs == []
