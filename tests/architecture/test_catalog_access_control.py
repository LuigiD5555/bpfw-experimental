"""Catalog access control: lock blocks writes, not reads/validation."""

from pathlib import Path
from unittest.mock import patch

import pytest

from bpfw.catalog.access_control import (
    CatalogLockedError,
    CatalogStateCheckError,
    ExternalCatalogWriteBlockedError,
    assert_catalog_write_scope,
    assert_catalog_writable,
    is_catalog_locked,
)
from bpfw.catalog.loader import (
    load_catalog_documents,
    load_catalog_snapshot,
    load_extended_catalog_snapshot,
)


_LOCKED_STATE = {
    "status": "locked",
    "lock_backend": "linux_immutable",
    "opened_at": None,
    "watcher_active": False,
    "last_event": None,
    "last_error": None,
}

_UNLOCKED_STATE = {
    "status": "unlocked",
    "lock_backend": None,
    "opened_at": "2026-04-12T12:00:00+00:00",
    "watcher_active": False,
    "last_event": None,
    "last_error": None,
}


def _write_valid_responsibility_yaml(tmp_path: Path) -> Path:
    yaml_file = tmp_path / "search.yaml"
    yaml_file.write_text(
        "\n".join(
            [
                "responsibility_id: resp.search",
                "canonical_name: Search",
                "owner_layer: application",
                "is_public: false",
                "official_port: null",
                "public_entrypoints: []",
                "allowed_components:",
                "  - src.application.search",
                "allowed_implementations:",
                "  - src.application.search.SearchImplementation",
                "active_implementation: src.application.search.SearchImplementation",
                "lifecycle_state: active",
                "allowed_replacements: []",
                "forbidden_direct_instantiation: []",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return yaml_file


def test_assert_catalog_writable_passes_when_unlocked() -> None:
    """When guard state is 'unlocked', assertion passes."""
    with patch("bpfw.catalog.access_control.read_state_file", return_value=_UNLOCKED_STATE):
        assert_catalog_writable()  # must not raise


def test_assert_catalog_writable_fails_when_locked() -> None:
    """When guard state is 'locked', assertion raises CatalogLockedError."""
    with patch("bpfw.catalog.access_control.read_state_file", return_value=_LOCKED_STATE):
        with pytest.raises(
            CatalogLockedError,
            match="Catalog is locked for writes. Unlock or use SUDO authorization.",
        ):
            assert_catalog_writable()


def test_assert_catalog_writable_passes_when_state_file_missing() -> None:
    """When state file does not exist, treat as unlocked (backward compat)."""
    from bpfw.catalog.state_file import CatalogGuardStateFileNotFoundError

    with patch(
        "bpfw.catalog.access_control.read_state_file",
        side_effect=CatalogGuardStateFileNotFoundError(Path(".catalog/lockstate.json")),
    ):
        assert_catalog_writable()  # must not raise


def test_assert_catalog_writable_fails_on_state_read_error() -> None:
    """When state file cannot be read/parsed, raise CatalogStateCheckError."""
    with patch(
        "bpfw.catalog.access_control.read_state_file",
        side_effect=ValueError("invalid JSON"),
    ):
        with pytest.raises(CatalogStateCheckError, match="Cannot verify catalog"):
            assert_catalog_writable()


def test_is_catalog_locked_reflects_guard_state() -> None:
    with (
        patch("bpfw.catalog.access_control.read_state_file", return_value=_LOCKED_STATE),
    ):
        assert is_catalog_locked() is True
    with (
        patch("bpfw.catalog.access_control.read_state_file", return_value=_UNLOCKED_STATE),
        patch("bpfw.catalog.access_control.list_catalog_yaml_files", return_value=[]),
        patch("bpfw.catalog.access_control.verify_write_block", return_value=False),
    ):
        assert is_catalog_locked() is False
    with (
        patch("bpfw.catalog.access_control.read_state_file", return_value=_LOCKED_STATE),
        patch("bpfw.catalog.access_control.list_catalog_yaml_files", return_value=[]),
        patch("bpfw.catalog.access_control.verify_write_block", return_value=True),
    ):
        assert is_catalog_locked() is True


def test_is_catalog_locked_fails_when_state_locked_but_files_writable() -> None:
    with (
        patch("bpfw.catalog.access_control.read_state_file", return_value=_LOCKED_STATE),
        patch("bpfw.catalog.access_control.list_catalog_yaml_files", return_value=[Path("catalog.yaml")]),
        patch("bpfw.catalog.access_control.verify_write_block", return_value=False),
    ):
        with pytest.raises(CatalogStateCheckError, match="lockstate says 'locked'"):
            is_catalog_locked()


def test_is_catalog_locked_fails_when_state_unlocked_but_files_blocked() -> None:
    with (
        patch("bpfw.catalog.access_control.read_state_file", return_value=_UNLOCKED_STATE),
        patch("bpfw.catalog.access_control.list_catalog_yaml_files", return_value=[Path("catalog.yaml")]),
        patch("bpfw.catalog.access_control.verify_write_block", return_value=True),
    ):
        with pytest.raises(CatalogStateCheckError, match="lockstate says 'unlocked'"):
            is_catalog_locked()


def test_assert_catalog_write_scope_allows_matching_explicit_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BPFW_PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("BPFW_ALLOW_EXTERNAL_CATALOG_WRITES", raising=False)
    with patch("bpfw.catalog.access_control.Path.cwd", return_value=tmp_path):
        assert_catalog_write_scope()


def test_assert_catalog_write_scope_blocks_external_root_by_default(monkeypatch, tmp_path: Path) -> None:
    external_root = tmp_path / "external-project"
    external_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("BPFW_PROJECT_ROOT", str(external_root))
    monkeypatch.delenv("BPFW_ALLOW_EXTERNAL_CATALOG_WRITES", raising=False)
    with patch("bpfw.catalog.access_control.Path.cwd", return_value=tmp_path):
        with pytest.raises(ExternalCatalogWriteBlockedError, match="External catalog write blocked"):
            assert_catalog_write_scope()


def test_assert_catalog_write_scope_allows_external_when_opted_in(monkeypatch, tmp_path: Path) -> None:
    external_root = tmp_path / "external-project"
    external_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("BPFW_PROJECT_ROOT", str(external_root))
    monkeypatch.setenv("BPFW_ALLOW_EXTERNAL_CATALOG_WRITES", "1")
    with patch("bpfw.catalog.access_control.Path.cwd", return_value=tmp_path):
        assert_catalog_write_scope()


def test_load_catalog_documents_succeeds_when_locked(tmp_path: Path) -> None:
    """Locked catalog can still be read and parsed."""
    yaml_file = _write_valid_responsibility_yaml(tmp_path)
    with (
        patch("bpfw.catalog.access_control.read_state_file", return_value=_LOCKED_STATE),
        patch("bpfw.catalog.loader.list_catalog_yaml_files", return_value=[yaml_file]),
    ):
        docs = load_catalog_documents()
        assert len(docs) == 1
        assert docs[0]["responsibility_id"] == "resp.search"


def test_load_catalog_snapshot_succeeds_when_locked(tmp_path: Path) -> None:
    yaml_file = _write_valid_responsibility_yaml(tmp_path)
    with (
        patch("bpfw.catalog.access_control.read_state_file", return_value=_LOCKED_STATE),
        patch("bpfw.catalog.loader.list_catalog_yaml_files", return_value=[yaml_file]),
    ):
        snapshot = load_catalog_snapshot()
    assert len(snapshot.responsibilities) == 1
    assert snapshot.responsibilities[0].responsibility_id == "resp.search"


def test_load_extended_catalog_snapshot_succeeds_when_locked(tmp_path: Path) -> None:
    yaml_file = _write_valid_responsibility_yaml(tmp_path)
    with (
        patch("bpfw.catalog.access_control.read_state_file", return_value=_LOCKED_STATE),
        patch("bpfw.catalog.loader.list_catalog_yaml_files", return_value=[yaml_file]),
        patch("bpfw.catalog.loader.list_policy_yaml_files", return_value=[]),
        patch("bpfw.catalog.loader.list_contract_yaml_files", return_value=[]),
        patch("bpfw.catalog.loader.list_type_yaml_files", return_value=[]),
        patch("bpfw.catalog.loader.list_operation_yaml_files", return_value=[]),
        patch("bpfw.catalog.loader.list_binding_yaml_files", return_value=[]),
        patch("bpfw.catalog.loader.list_interaction_yaml_files", return_value=[]),
    ):
        extended_snapshot = load_extended_catalog_snapshot()
    assert len(extended_snapshot.responsibilities) == 1
