"""Tests for the mechanical Blueprint Engine facade."""

from pathlib import Path

import yaml

from bpfw.core.blueprint_engine import (
    BlueprintChangeKind,
    BlueprintChangeRequest,
    BlueprintChangeSource,
    BlueprintEngine,
    MechanicalChangeEvidence,
)
from bpfw.core.authority.patch import PatchWriteContext


def _write_blueprint(project_root: Path, includes: list[str] | None = None) -> None:
    """Write a minimal root blueprint file."""
    blueprint_path = project_root / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "project": {"id": "test", "name": "test", "source_roots": ["src"]},
        "authority": {
            "layout": "sharded",
            "shard_strategy": "domain",
            "default_shard": "bpfw/blocks/core.yaml",
        },
    }
    if includes is not None:
        data["includes"] = includes
    blueprint_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _write_shard(project_root: Path, relative_path: str, blocks: list[dict]) -> None:
    """Write one authority shard file."""
    shard_path = project_root / relative_path
    shard_path.parent.mkdir(parents=True, exist_ok=True)
    shard_path.write_text(yaml.safe_dump({"blocks": blocks}, sort_keys=False), encoding="utf-8")


def _read_yaml(path: Path) -> dict:
    """Read a YAML file as a dictionary."""
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _block() -> dict:
    """Return a valid authority block with a code reference."""
    return {
        "id": "reports.ReportGenerator",
        "name": "ReportGenerator",
        "purpose": "generate reports",
        "domain": "reports",
        "lifecycle": "active",
        "code": {
            "path": "src/app/reports.py",
            "symbol": "ReportGenerator",
            "kind": "class",
        },
    }


def _context() -> PatchWriteContext:
    """Return a write context suitable for tests."""
    return PatchWriteContext(tool_name="test", allow_guarded_writes=True)


def test_blocks_unconfirmed_create_block(tmp_path: Path) -> None:
    """Ensure new blocks require human confirmation."""
    _write_blueprint(tmp_path, includes=["bpfw/blocks/core.yaml"])
    _write_shard(tmp_path, "bpfw/blocks/core.yaml", [])

    engine = BlueprintEngine(tmp_path)
    request = BlueprintChangeRequest(
        kind=BlueprintChangeKind.CREATE_BLOCK,
        source=BlueprintChangeSource.INSPECTOR,
        payload={
            "block_data": _block(),
            "target_shard_path": "bpfw/blocks/core.yaml",
        },
    )

    preview = engine.preview_change(request)

    assert not preview.allowed
    assert preview.blocked_reason == "Blueprint Engine requires human confirmation for this change."


def test_applies_human_confirmed_create_block(tmp_path: Path) -> None:
    """Apply a human-confirmed block creation to a shard."""
    _write_blueprint(tmp_path, includes=["bpfw/blocks/core.yaml"])
    _write_shard(tmp_path, "bpfw/blocks/core.yaml", [])

    engine = BlueprintEngine(tmp_path)
    request = BlueprintChangeRequest(
        kind=BlueprintChangeKind.CREATE_BLOCK,
        source=BlueprintChangeSource.INSPECTOR,
        human_confirmed=True,
        payload={
            "block_data": _block(),
            "target_shard_path": "bpfw/blocks/core.yaml",
        },
    )

    result = engine.apply_change(request, _context())
    shard = _read_yaml(tmp_path / "bpfw" / "blocks" / "core.yaml")

    assert result.success
    assert shard["blocks"][0]["id"] == "reports.ReportGenerator"


def test_applies_safe_mechanical_code_reference_update(tmp_path: Path) -> None:
    """Apply an exact mechanical moved-and-renamed update without human confirmation."""
    _write_blueprint(tmp_path, includes=["bpfw/blocks/core.yaml"])
    _write_shard(tmp_path, "bpfw/blocks/core.yaml", [_block()])

    engine = BlueprintEngine(tmp_path)
    request = BlueprintChangeRequest(
        kind=BlueprintChangeKind.UPDATE_CODE_REFERENCE,
        source=BlueprintChangeSource.SAFE_MECHANICAL_UPDATE,
        mechanical_evidence=MechanicalChangeEvidence(
            exact_content_match=True,
            one_to_one_match=True,
            symbol_kind_matches=True,
            purpose_preserved=True,
        ),
        payload={
            "block_id": "reports.ReportGenerator",
            "source_shard_path": "bpfw/blocks/core.yaml",
            "new_path": "src/app/reports/generator.py",
            "new_symbol": "CustomerReportGenerator",
            "new_kind": "class",
            "new_name": "CustomerReportGenerator",
        },
    )

    result = engine.apply_change(request, _context())
    shard = _read_yaml(tmp_path / "bpfw" / "blocks" / "core.yaml")
    block = shard["blocks"][0]

    assert result.success
    assert block["name"] == "CustomerReportGenerator"
    assert block["code"]["path"] == "src/app/reports/generator.py"
    assert block["code"]["symbol"] == "CustomerReportGenerator"
    assert block["purpose"] == "generate reports"


def test_rejects_unsafe_mechanical_code_reference_update(tmp_path: Path) -> None:
    """Reject a mechanical update when exact evidence is missing."""
    _write_blueprint(tmp_path, includes=["bpfw/blocks/core.yaml"])
    _write_shard(tmp_path, "bpfw/blocks/core.yaml", [_block()])

    engine = BlueprintEngine(tmp_path)
    request = BlueprintChangeRequest(
        kind=BlueprintChangeKind.UPDATE_CODE_REFERENCE,
        source=BlueprintChangeSource.SAFE_MECHANICAL_UPDATE,
        mechanical_evidence=MechanicalChangeEvidence(
            exact_content_match=False,
            one_to_one_match=True,
            symbol_kind_matches=True,
            purpose_preserved=True,
        ),
        payload={
            "block_id": "reports.ReportGenerator",
            "source_shard_path": "bpfw/blocks/core.yaml",
            "new_path": "src/app/reports/generator.py",
            "new_symbol": "CustomerReportGenerator",
        },
    )

    preview = engine.preview_change(request)

    assert not preview.allowed
    assert preview.blocked_reason == "Safe mechanical update requires exact one-to-one evidence."
