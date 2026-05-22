from pathlib import Path

import yaml

from bpfw.core.catalog.domain import BlueprintMapper, BlueprintRepository


def test_blueprint_mapper_round_trip_preserves_core_fields() -> None:
    mapper = BlueprintMapper()
    raw = {
        "version": 1,
        "project": {"source_roots": ["src"], "ignored_paths": ["tests"]},
        "policy": {"allowed_statuses": ["active", "legacy"], "one_active_block_per_purpose": True},
        "authority": {"layout": "sharded"},
        "includes": ["bpfw/blocks/core.yaml"],
        "blocks": [
            {
                "id": "service_loader",
                "purpose": "  Load Service  ",
                "domain": " Core ",
                "name": "ServiceLoader",
                "status": "ACTIVE",
                "code": {"path": "src/app.py", "symbol": "ServiceLoader", "kind": "class"},
                "connections": [{"target": "logger", "meaning": "uses"}],
            }
        ],
    }

    document = mapper.from_raw(raw)
    dumped = mapper.to_raw(document)

    assert document.blocks[0].purpose == "load service"
    assert document.blocks[0].domain == "core"
    assert document.blocks[0].lifecycle == "active"
    assert dumped["blocks"][0]["code"]["kind"] == "class"
    assert dumped["blocks"][0]["status"] == "active"


def test_blueprint_repository_loads_simple_blueprint(tmp_path: Path) -> None:
    bpfw_dir = tmp_path / "bpfw"
    bpfw_dir.mkdir(parents=True)
    blueprint_path = bpfw_dir / "blueprint.yaml"
    blueprint_path.write_text(
        "version: 1\n"
        "project:\n"
        "  source_roots:\n"
        "    - src\n"
        "blocks:\n"
        "  - id: demo\n"
        "    purpose: demo purpose\n"
        "    domain: core\n"
        "    name: Demo\n"
        "    status: active\n"
        "    code:\n"
        "      path: src/demo.py\n"
        "      symbol: Demo\n"
        "      kind: class\n",
        encoding="utf-8",
    )

    result = BlueprintRepository(project_root=tmp_path).load()

    assert result.document.blocks
    assert result.document.blocks[0].identifier == "demo"
    assert result.raw_data["blocks"][0]["id"] == "demo"


def test_blueprint_repository_loads_sharded_layout_without_authority_directory(tmp_path: Path) -> None:
    bpfw_dir = tmp_path / "bpfw"
    blocks_dir = bpfw_dir / "blocks"
    blocks_dir.mkdir(parents=True)

    (bpfw_dir / "blueprint.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "project": {"id": "demo"},
                "authority": {"layout": "sharded", "default_shard": "bpfw/blocks/core.yaml"},
                "includes": ["bpfw/blocks/core.yaml"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (blocks_dir / "core.yaml").write_text(
        yaml.safe_dump(
            {
                "blocks": [
                    {
                        "id": "demo",
                        "purpose": "demo purpose",
                        "domain": "core",
                        "name": "Demo",
                        "status": "active",
                        "code": {"path": "src/demo.py", "symbol": "Demo", "kind": "class"},
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = BlueprintRepository(project_root=tmp_path).load()

    assert result.authority_document is not None
    assert result.document.blocks
    assert result.document.blocks[0].identifier == "demo"
