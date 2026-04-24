"""Lock semantics: read/validate allowed, write-like paths blocked."""

from pathlib import Path
from unittest.mock import patch

from bpfw.architecture import checker
from bpfw.architecture.validate_migration import run_validation

_LOCKED_STATE = {
    "status": "locked",
    "lock_backend": "linux_immutable",
    "opened_at": None,
    "watcher_active": False,
    "last_event": None,
    "last_error": None,
}


def _write_valid_catalog(root_path: Path) -> Path:
    source_directory = root_path / "src" / "application"
    source_directory.mkdir(parents=True, exist_ok=True)
    (source_directory / "__init__.py").write_text("", encoding="utf-8")
    (source_directory / "search.py").write_text(
        "\n".join(
            [
                "class SearchImplementation:",
                "    pass",
                "",
            ]
        ),
        encoding="utf-8",
    )

    catalog_file = root_path / "search.yaml"
    catalog_file.write_text(
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
    return catalog_file


def test_locked_catalog_can_be_validated(tmp_path: Path) -> None:
    catalog_file = _write_valid_catalog(tmp_path)
    with (
        patch("bpfw.catalog.access_control.read_state_file", return_value=_LOCKED_STATE),
        patch("bpfw.catalog.loader.list_catalog_yaml_files", return_value=[catalog_file]),
    ):
        assert checker._check_catalog_loads() == []


def test_locked_catalog_blocks_auto_refresh_write_path(caplog) -> None:
    with (
        patch("bpfw.catalog.runtime_snapshot.load_persisted_runtime_snapshot", return_value=None),
        patch("bpfw.catalog.access_control.read_state_file", return_value=_LOCKED_STATE),
        patch("bpfw.architecture.validate_migration._refresh_snapshot_via_project_adapter") as refresh_mock,
    ):
        exit_code = run_validation(refresh_snapshot=True)

    refresh_mock.assert_not_called()
    assert exit_code == 1
    assert "Catalog is locked for writes. Unlock or use SUDO authorization." in caplog.text


def test_external_write_scope_blocks_auto_refresh_write_path(
    monkeypatch,
    tmp_path: Path,
    caplog,
) -> None:
    external_root = tmp_path / "external-rag-project"
    external_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BPFW_PROJECT_ROOT", str(external_root))
    monkeypatch.delenv("BPFW_ALLOW_EXTERNAL_CATALOG_WRITES", raising=False)
    with (
        patch("bpfw.catalog.runtime_snapshot.load_persisted_runtime_snapshot", return_value=None),
        patch("bpfw.architecture.validate_migration._refresh_snapshot_via_project_adapter") as refresh_mock,
    ):
        exit_code = run_validation(refresh_snapshot=True)

    refresh_mock.assert_not_called()
    assert exit_code == 1
    assert "External catalog write blocked" in caplog.text


def test_check_architecture_core_checks_run_when_catalog_locked(tmp_path: Path) -> None:
    catalog_file = _write_valid_catalog(tmp_path)
    with (
        patch("bpfw.catalog.access_control.read_state_file", return_value=_LOCKED_STATE),
        patch("bpfw.catalog.loader.list_catalog_yaml_files", return_value=[catalog_file]),
        patch("bpfw.architecture.checker._REPO_ROOT", tmp_path),
        patch("bpfw.architecture.checker.load_persisted_runtime_snapshot", return_value=None),
    ):
        undeclared_module_violations = checker._check_undeclared_modules()
        runtime_contract_violations = checker._check_runtime_contract()
        wiring_violations = checker._check_wiring_verifier()
        implementation_violations = checker._check_declared_implementation_existence()

    assert undeclared_module_violations == []
    assert runtime_contract_violations == []
    assert wiring_violations == []
    assert implementation_violations == []
