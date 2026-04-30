import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from bpfw.core.registry import AuthoritySealPrecheckStep, build_default_registry
from bpfw.core.result import ResultStatus
from bpfw.integrity.hash_provider import compute_sha256


def _context(project_root: Path, init_accept_scan: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        project_root=project_root,
        command_arguments={"init_accept_scan": "true" if init_accept_scan else "false"},
    )


def _write_manifest_with_blueprint_hash(project_root: Path, expected_text: str) -> None:
    manifest_path = project_root / ".bpfw/manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    blueprint_path = project_root / "blueprint.yaml"
    blueprint_path.write_text(expected_text, encoding="utf-8")
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


def _write_active_grant(project_root: Path, grant_id: str, resource_id: str) -> None:
    grants_dir = project_root / ".bpfw/access_grants"
    grants_dir.mkdir(parents=True, exist_ok=True)
    now_utc = datetime.now(tz=timezone.utc)
    payload = {
        "grant_id": grant_id,
        "request_id": "access-request-001",
        "resource_id": resource_id,
        "resource_path": "blueprint.yaml",
        "operation": "add_allowed_file",
        "scope": "query_execution",
        "granted_by": "tester",
        "created_at": now_utc.isoformat(),
        "expires_at": (now_utc + timedelta(minutes=30)).isoformat(),
        "signature": "dummy",
    }
    (grants_dir / f"{grant_id}.json").write_text(f"{json.dumps(payload, ensure_ascii=True)}\n", encoding="utf-8")


def _write_audit_event(project_root: Path, resource_id: str, grant_id: str) -> None:
    audit_path = project_root / ".bpfw/audit/authority-events.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "event_type": "authority_change_applied",
        "resource_id": resource_id,
        "operation": "add_allowed_file",
        "scope": "query_execution",
        "grant_id": grant_id,
        "timestamp": "2026-01-01T00:00:00+00:00",
    }
    audit_path.write_text(f"{json.dumps(event, ensure_ascii=True)}\n", encoding="utf-8")


def test_rule_1_no_manifest_and_not_initialized_blocks(tmp_path: Path) -> None:
    result = AuthoritySealPrecheckStep().run(_context(tmp_path, init_accept_scan=False))
    assert result.status == ResultStatus.BLOCK
    assert "Project is not sealed yet" in result.message


def test_rule_2_init_creating_first_baseline_allows(tmp_path: Path) -> None:
    result = AuthoritySealPrecheckStep().run(_context(tmp_path, init_accept_scan=True))
    assert result.status == ResultStatus.OK


def test_rule_3_authority_changed_without_audit_event_blocks(tmp_path: Path) -> None:
    _write_manifest_with_blueprint_hash(tmp_path, "version: 1\n")
    (tmp_path / "blueprint.yaml").write_text("version: 2\n", encoding="utf-8")
    result = AuthoritySealPrecheckStep().run(_context(tmp_path))
    assert result.status == ResultStatus.BLOCK
    assert "changed outside controlled authority operation" in result.message
    assert "- blueprint.yaml" in result.message


def test_rule_4_authority_changed_with_invalid_grant_blocks(tmp_path: Path) -> None:
    _write_manifest_with_blueprint_hash(tmp_path, "version: 1\n")
    (tmp_path / "blueprint.yaml").write_text("version: 2\n", encoding="utf-8")
    _write_audit_event(tmp_path, resource_id="project_blueprint", grant_id="access-grant-999")
    result = AuthoritySealPrecheckStep().run(_context(tmp_path))
    assert result.status == ResultStatus.BLOCK
    assert "invalid authority grant" in result.message


def test_rule_5_authority_changed_with_valid_grant_allows(tmp_path: Path) -> None:
    _write_manifest_with_blueprint_hash(tmp_path, "version: 1\n")
    (tmp_path / "blueprint.yaml").write_text("version: 2\n", encoding="utf-8")
    _write_audit_event(tmp_path, resource_id="project_blueprint", grant_id="access-grant-001")
    _write_active_grant(tmp_path, grant_id="access-grant-001", resource_id="project_blueprint")
    result = AuthoritySealPrecheckStep().run(_context(tmp_path))
    assert result.status == ResultStatus.OK


def test_manifest_write_pipeline_wiring_contains_seal_precheck_before_manifest_write() -> None:
    manifest_pipeline = build_default_registry()["manifest_write"]
    step_names = [step.name for step in manifest_pipeline.steps]
    assert "authority.seal_precheck" in step_names
    assert "integrity.manifest.write" in step_names
    assert step_names.index("authority.seal_precheck") < step_names.index("integrity.manifest.write")
