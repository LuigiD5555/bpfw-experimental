from pathlib import Path

import yaml

from bpfw.catalog.access_control import authorize_blueprint_writes_for_tool
from bpfw.catalog.verify import run_verify
from bpfw.reports.status_report import run_status


def _write_demo_source(project_root: Path) -> None:
    """Create a minimal Python source file used by read-only authority tests."""

    source_path = project_root / "src" / "demo"
    source_path.mkdir(parents=True)
    (source_path / "app.py").write_text(
        "def declared_func():\n"
        "    return 1\n",
        encoding="utf-8",
    )


def _complete_declared_block() -> dict:
    """Build a complete authority block for the demo source function."""

    return {
        "id": "declared_func",
        "purpose": "maintain declared func",
        "name": "declared_func",
        "domain": "demo",
        "status": "active",
        "code": {
            "path": "src/demo/app.py",
            "module": "demo.app",
            "symbol": "declared_func",
            "kind": "function",
            "start_line": 1,
            "end_line": 2,
        },
    }


def _write_sharded_index(project_root: Path, includes: list[str]) -> None:
    """Create a sharded root authority index for a temporary project."""

    blueprint_path = project_root / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "project": {
                    "id": "demo_project",
                    "name": "demo-project",
                    "source_roots": ["src"],
                },
                "authority": {
                    "layout": "sharded",
                    "shard_strategy": "domain",
                    "default_shard": "bpfw/blocks/core.yaml",
                    "auto_create_shards": True,
                },
                "includes": includes,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_verify_does_not_auto_update_blueprint_for_layout_drift(tmp_path: Path) -> None:
    """Verify must detect drift but must not auto-update blueprint or create new shard files."""

    _write_demo_source(project_root=tmp_path)
    _write_sharded_index(project_root=tmp_path, includes=["bpfw/blocks/core.yaml"])

    core_shard_path = tmp_path / "bpfw" / "blocks" / "core.yaml"
    core_shard_path.parent.mkdir(parents=True)
    core_shard_path.write_text(
        yaml.safe_dump({"blocks": [_complete_declared_block()]}, sort_keys=False),
        encoding="utf-8",
    )

    original_index = yaml.safe_load(
        (tmp_path / "bpfw" / "blueprint.yaml").read_text(encoding="utf-8")
    )

    report, _exit_code = run_verify(project_root=tmp_path)

    # Verify must not modify the index
    current_index = yaml.safe_load(
        (tmp_path / "bpfw" / "blueprint.yaml").read_text(encoding="utf-8")
    )
    assert current_index["includes"] == original_index["includes"]

    # Verify must not create new shard files
    assert not (tmp_path / "bpfw" / "blocks" / "demo.yaml").exists()


def test_status_does_not_auto_update_blueprint_for_legacy_blocks(tmp_path: Path) -> None:
    """Status must not auto-update legacy root-level blocks."""

    _write_demo_source(project_root=tmp_path)
    _write_sharded_index(project_root=tmp_path, includes=["bpfw/blocks/core.yaml"])
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_data = yaml.safe_load(blueprint_path.read_text(encoding="utf-8"))
    blueprint_data["blocks"] = [_complete_declared_block()]
    blueprint_path.write_text(yaml.safe_dump(blueprint_data, sort_keys=False), encoding="utf-8")

    core_shard_path = tmp_path / "bpfw" / "blocks" / "core.yaml"
    core_shard_path.parent.mkdir(parents=True)
    core_shard_path.write_text(yaml.safe_dump({"blocks": []}, sort_keys=False), encoding="utf-8")

    run_status(project_root=tmp_path)

    # Status must not modify the blueprint
    current_index = yaml.safe_load(blueprint_path.read_text(encoding="utf-8"))
    assert "blocks" in current_index

    # Status must not create new shard files
    assert not (tmp_path / "bpfw" / "blocks" / "demo.yaml").exists()



def test_blueprint_engine_does_not_purge_ghost_blocks_automatically(tmp_path: Path) -> None:
    """Blueprint Engine must not delete missing-code declarations without a decision."""

    _write_demo_source(project_root=tmp_path)
    _write_sharded_index(project_root=tmp_path, includes=["bpfw/blocks/core.yaml"])

    ghost_block = {
        "id": "ghost_func",
        "purpose": "does not exist",
        "name": "ghost_func",
        "domain": "demo",
        "status": "active",
        "code": {
            "path": "src/ghost/missing.py",
            "module": "ghost.missing",
            "symbol": "ghost_func",
            "kind": "function",
            "start_line": 1,
            "end_line": 2,
        },
    }

    core_shard_path = tmp_path / "bpfw" / "blocks" / "core.yaml"
    core_shard_path.parent.mkdir(parents=True)
    core_shard_path.write_text(
        yaml.safe_dump(
            {"blocks": [_complete_declared_block(), ghost_block]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from bpfw.catalog.verify import run_verify

    run_verify(project_root=tmp_path)

    updated_shard = yaml.safe_load(core_shard_path.read_text(encoding="utf-8"))
    block_ids = [block["id"] for block in updated_shard.get("blocks", [])]
    assert "ghost_func" in block_ids
