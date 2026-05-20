from pathlib import Path

import yaml

from bpfw.catalog.verify import run_verify
from bpfw.reports.status_report import run_status


def _write_demo_source(project_root: Path) -> None:
    """Create a minimal Python source file used by authority synchronization tests."""

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


def test_verify_automatically_reshards_small_layout_drift(tmp_path: Path) -> None:
    """Verify should apply safe shard synchronization before reporting drift."""

    _write_demo_source(project_root=tmp_path)
    _write_sharded_index(project_root=tmp_path, includes=["bpfw/blocks/core.yaml"])

    core_shard_path = tmp_path / "bpfw" / "blocks" / "core.yaml"
    core_shard_path.parent.mkdir(parents=True)
    core_shard_path.write_text(
        yaml.safe_dump({"blocks": [_complete_declared_block()]}, sort_keys=False),
        encoding="utf-8",
    )

    report, exit_code = run_verify(project_root=tmp_path)

    migrated_index = yaml.safe_load((tmp_path / "bpfw" / "blueprint.yaml").read_text(encoding="utf-8"))
    migrated_demo_shard = yaml.safe_load((tmp_path / "bpfw" / "blocks" / "demo.yaml").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report.allowed is True
    assert "bpfw/blocks/demo.yaml" in migrated_index["includes"]
    assert migrated_demo_shard["blocks"][0]["id"] == "declared_func"


def test_status_migrates_legacy_root_blocks_before_loading_authority(tmp_path: Path) -> None:
    """Status should normalize legacy root-level blocks instead of reporting invalid authority."""

    _write_demo_source(project_root=tmp_path)
    _write_sharded_index(project_root=tmp_path, includes=["bpfw/blocks/core.yaml"])
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_data = yaml.safe_load(blueprint_path.read_text(encoding="utf-8"))
    blueprint_data["blocks"] = [_complete_declared_block()]
    blueprint_path.write_text(yaml.safe_dump(blueprint_data, sort_keys=False), encoding="utf-8")

    core_shard_path = tmp_path / "bpfw" / "blocks" / "core.yaml"
    core_shard_path.parent.mkdir(parents=True)
    core_shard_path.write_text(yaml.safe_dump({"blocks": []}, sort_keys=False), encoding="utf-8")

    output, exit_code = run_status(project_root=tmp_path)

    migrated_index = yaml.safe_load(blueprint_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert "state: defined" in output
    assert "blocks" not in migrated_index
    assert (tmp_path / "bpfw" / "blocks" / "demo.yaml").exists()
