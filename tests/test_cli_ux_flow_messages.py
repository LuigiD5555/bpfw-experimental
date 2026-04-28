from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from bpfw.core.registry import InitProjectStep, VerifyAuthorityStep
from bpfw.core.result import ResultStatus
from bpfw.integrity.hash_provider import compute_sha256


def _context(project_root: Path, **arguments: str) -> SimpleNamespace:
    return SimpleNamespace(project_root=project_root, command_arguments=arguments)


def test_init_new_project_uses_short_ux_message(tmp_path: Path) -> None:
    from bpfw.authority.lock_manager import AuthorityLockManager

    original_lock_all = AuthorityLockManager.lock_all
    AuthorityLockManager.lock_all = lambda self, project_root: 1  # type: ignore[method-assign]
    try:
        result = InitProjectStep().run(_context(tmp_path))
    finally:
        AuthorityLockManager.lock_all = original_lock_all  # type: ignore[method-assign]
    assert result.status == ResultStatus.OK
    assert result.message == (
        "New project detected.\n"
        "Created protected baseline.\n"
        "Protection active by default."
    )


def test_init_existing_project_uses_scan_ux_message(tmp_path: Path) -> None:
    source_file = tmp_path / "src/application/use_case.py"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("def execute() -> None:\n    return None\n", encoding="utf-8")

    result = InitProjectStep().run(_context(tmp_path))
    assert result.status == ResultStatus.INFO
    assert result.message == (
        "Existing project detected.\n"
        "Mechanical scan completed.\n"
        "Generated blueprint.generated.yaml.\n"
        "Generated architecture.generated.yaml.\n"
        "Generated scan_report.md."
    )


def test_verify_authority_drift_uses_critical_ux_message(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "blueprint.yaml"
    architecture_path = tmp_path / "architecture.yaml"
    manifest_path = tmp_path / ".bpfw/manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    blueprint_path.write_text("version: 1\n", encoding="utf-8")
    architecture_path.write_text("version: 1\n", encoding="utf-8")

    manifest_payload = {
        "version": 1,
        "updated_at": "2026-01-01T00:00:00+00:00",
        "files": [
            {
                "path": "blueprint.yaml",
                "resource_id": "project_blueprint",
                "sha256": compute_sha256(blueprint_path),
                "size": blueprint_path.stat().st_size,
            }
        ],
        "signature": "fake",
    }
    manifest_path.write_text(f"{json.dumps(manifest_payload, ensure_ascii=True)}\n", encoding="utf-8")

    blueprint_path.write_text("version: 2\n", encoding="utf-8")
    result = VerifyAuthorityStep().run(_context(tmp_path))

    assert result.status == ResultStatus.CRITICAL
    assert result.message == (
        "CRITICAL\n\n"
        "Authority drift detected.\n\n"
        "Resource:\n"
        "blueprint.yaml\n\n"
        "Direct authority edits are not allowed.\n\n"
        "Do not retry this edit.\n\n"
        "Allowed next action:\n"
        "Revert the manual edit and use proposal/access flow."
    )
