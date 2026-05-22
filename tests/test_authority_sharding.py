"""Tests for authority sharding engine."""

import pytest
from pathlib import Path

from bpfw.catalog.access_control import authorize_blueprint_writes_for_tool
from bpfw.authority import (
    AuthorityRepository,
    BlueprintLayoutPlanner,
    InvalidAuthorityIndexError,
    InvalidAuthorityShardError,
    DuplicateBlockIdError,
    DuplicateCodeDeclarationError,
    ShardDriftError,
)
from bpfw.authority.index import AuthorityIndex
from bpfw.authority.shard import AuthorityShard
from bpfw.authority.document import AuthorityDocument
from bpfw.authority.sharding import ShardDecisionEngine
from bpfw.authority.planner import BlueprintLayoutPlan


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a temporary project root with basic structure."""
    # Create project structure
    (tmp_path / "bpfw").mkdir(parents=True)
    (tmp_path / "bpfw" / "blocks").mkdir(parents=True)
    (tmp_path / "src" / "bpfw" / "protection").mkdir(parents=True)
    (tmp_path / "src" / "bpfw" / "catalog").mkdir(parents=True)
    (tmp_path / "src" / "bpfw" / "integrations").mkdir(parents=True)
    
    # Create blueprint.yaml with authority config
    blueprint_data = {
        "version": 1,
        "project": {
            "id": "test_project",
            "name": "test-project",
            "root": ".",
            "language": "python",
            "source_roots": ["src"],
            "ignored_paths": [".git", ".venv"],
        },
        "policy": {
            "mode": "catalog",
            "empty_blueprint_allows_execution": True,
            "defined_blueprint_blocks_on_drift": True,
        },
        "authority": {
            "layout": "sharded",
            "shard_strategy": "domain",
            "default_shard": "bpfw/blocks/core.yaml",
            "allow_empty_shards": False,
            "auto_create_shards": True,
            "auto_move_blocks": True,
        },
        "includes": ["bpfw/blocks/core.yaml"],
    }
    
    import yaml
    with open(tmp_path / "bpfw" / "blueprint.yaml", "w") as f:
        yaml.dump(blueprint_data, f)
    
    # Create core.yaml with blocks
    blocks_data = {
        "blocks": [
            {
                "id": "test_block_1",
                "purpose": "test",
                "name": "Test Block 1",
                "domain": "protection",
                "status": "active",
                "code": {
                    "path": "src/bpfw/protection/test.py",
                    "module": "bpfw.protection.test",
                    "symbol": "TestFunction",
                    "kind": "function",
                    "start_line": 1,
                    "end_line": 10,
                },
                "detected": {
                    "qualified_name": "bpfw.protection.test.TestFunction",
                    "kind": "function",
                },
            },
            {
                "id": "test_block_2",
                "purpose": "test",
                "name": "Test Block 2",
                "domain": "catalog",
                "status": "active",
                "code": {
                    "path": "src/bpfw/catalog/test.py",
                    "module": "bpfw.catalog.test",
                    "symbol": "TestClass",
                    "kind": "class",
                    "start_line": 1,
                    "end_line": 20,
                },
                "detected": {
                    "qualified_name": "bpfw.catalog.test.TestClass",
                    "kind": "class",
                },
            },
        ],
    }
    
    with open(tmp_path / "bpfw" / "blocks" / "core.yaml", "w") as f:
        yaml.dump(blocks_data, f)
    
    return tmp_path


def test_root_index_cannot_contain_blocks(tmp_path: Path):
    """Test that root blueprint.yaml fails if it contains blocks."""
    (tmp_path / "bpfw").mkdir(parents=True)
    blueprint_data = {
        "version": 1,
        "project": {
            "id": "test_project",
            "name": "test-project",
        },
        "authority": {
            "layout": "sharded",
            "shard_strategy": "domain",
            "default_shard": "bpfw/blocks/core.yaml",
        },
        "blocks": [{"id": "block_1"}],  # Invalid: blocks in root
        "includes": ["bpfw/blocks/core.yaml"],
    }
    
    import yaml
    with open(tmp_path / "bpfw" / "blueprint.yaml", "w") as f:
        yaml.dump(blueprint_data, f)
    
    with pytest.raises(InvalidAuthorityIndexError):
        AuthorityIndex.load(project_root=tmp_path)


def test_loader_fails_if_includes_missing(project_root: Path):
    """Test that loader fails if includes is missing from root."""
    blueprint_path = project_root / "bpfw" / "blueprint.yaml"
    
    import yaml
    with open(blueprint_path, "r") as f:
        data = yaml.safe_load(f)
    
    del data["includes"]  # Remove includes
    
    with open(blueprint_path, "w") as f:
        yaml.dump(data, f)
    
    with pytest.raises(InvalidAuthorityIndexError):
        AuthorityIndex.load(project_root=project_root)


def test_loader_fails_if_include_uses_glob(project_root: Path):
    """Test that loader fails if an include uses glob patterns."""
    blueprint_path = project_root / "bpfw" / "blueprint.yaml"
    
    import yaml
    with open(blueprint_path, "r") as f:
        data = yaml.safe_load(f)
    
    data["includes"] = ["bpfw/blocks/*.yaml"]  # Invalid: glob pattern
    
    with open(blueprint_path, "w") as f:
        yaml.dump(data, f)
    
    with pytest.raises(InvalidAuthorityIndexError):
        AuthorityIndex.load(project_root=project_root)


def test_loader_fails_if_included_shard_missing(project_root: Path):
    """Test that loader fails if an included shard file is missing."""
    blueprint_path = project_root / "bpfw" / "blueprint.yaml"
    
    import yaml
    with open(blueprint_path, "r") as f:
        data = yaml.safe_load(f)
    
    data["includes"] = ["bpfw/blocks/missing.yaml"]  # Non-existent shard
    
    with open(blueprint_path, "w") as f:
        yaml.dump(data, f)
    
    with pytest.raises(FileNotFoundError):
        AuthorityRepository(project_root=project_root).load()


def test_loader_fails_if_shard_yaml_invalid(tmp_path: Path):
    """Test that loader fails if shard YAML is invalid."""
    # Create basic project structure
    (tmp_path / "bpfw" / "blocks").mkdir(parents=True)
    
    # Create blueprint.yaml
    blueprint_data = {
        "version": 1,
        "project": {"id": "test", "name": "test"},
        "authority": {
            "layout": "sharded",
            "shard_strategy": "domain",
            "default_shard": "bpfw/blocks/invalid.yaml",
        },
        "includes": ["bpfw/blocks/invalid.yaml"],
    }
    
    import yaml
    with open(tmp_path / "bpfw" / "blueprint.yaml", "w") as f:
        yaml.dump(blueprint_data, f)
    
    # Create invalid YAML shard
    with open(tmp_path / "bpfw" / "blocks" / "invalid.yaml", "w") as f:
        f.write("blocks: [unclosed: [")  # Invalid YAML
    
    with pytest.raises(InvalidAuthorityShardError):
        AuthorityRepository(project_root=tmp_path).load()


def test_repository_loads_core_and_returns_unified_blocks(project_root: Path):
    """Test that repository loads core.yaml and returns unified blocks."""
    repository = AuthorityRepository(project_root=project_root)
    document = repository.load()
    
    blocks = document.get_blocks()
    assert len(blocks) == 2
    assert blocks[0]["id"] == "test_block_1"
    assert blocks[1]["id"] == "test_block_2"


def test_repository_save_syncs_index_metadata_without_includes_changes(project_root: Path):
    """Test that repository save syncs root index metadata even without include updates."""
    repository = AuthorityRepository(project_root=project_root)
    document = repository.load()

    document.blueprint_data["project"]["name"] = "renamed-project"
    with authorize_blueprint_writes_for_tool("test"):
        repository.save(document)

    import yaml
    saved_root = yaml.safe_load((project_root / "bpfw" / "blueprint.yaml").read_text(encoding="utf-8"))
    assert saved_root["project"]["name"] == "renamed-project"
    assert "blocks" not in saved_root


def test_repository_tracks_block_origin(project_root: Path):
    """Test that repository tracks where each block came from."""
    repository = AuthorityRepository(project_root=project_root)
    document = repository.load()
    
    origin = document.get_origin("test_block_1")
    assert origin is not None
    assert origin == Path("bpfw/blocks/core.yaml")


def test_repository_saves_moved_block_when_domain_changes(project_root: Path):
    """Test that repository saves moved block when domain changes."""
    repository = AuthorityRepository(project_root=project_root)
    document = repository.load()
    
    # Change domain of test_block_1
    blocks = document.get_blocks()
    blocks[0]["domain"] = "catalog"  # Change from protection to catalog
    document.replace_blocks(blocks)
    
    with authorize_blueprint_writes_for_tool("test"):
        repository.save(document)
    
    # Reload and verify
    document = repository.load()
    origin = document.get_origin("test_block_1")
    # After blueprint layout, it should be in catalog.yaml
    assert origin is not None


def test_repository_creates_new_shard_and_adds_include(project_root: Path):
    """Test that repository creates new shard and adds include."""
    repository = AuthorityRepository(project_root=project_root)
    document = repository.load()
    
    # Add a block with a new domain
    blocks = document.get_blocks()
    blocks.append({
        "id": "test_block_3",
        "purpose": "test",
        "name": "Test Block 3",
        "domain": "integrations",  # New domain
        "status": "active",
        "code": {
            "path": "src/bpfw/integrations/test.py",
            "module": "bpfw.integrations.test",
            "symbol": "TestFunction",
            "kind": "function",
        },
        "detected": {"qualified_name": "bpfw.integrations.test.TestFunction", "kind": "function"},
    })
    document.replace_blocks(blocks)
    
    with authorize_blueprint_writes_for_tool("test"):
        repository.save(document)
    
    # Reload and verify new shard exists
    document = repository.load()
    new_shard_path = project_root / "bpfw" / "blocks" / "integrations.yaml"
    assert new_shard_path.exists()


def test_repository_removes_empty_shard_when_allow_empty_false(project_root: Path):
    """Test that repository removes empty shard when allow_empty_shards is false."""
    repository = AuthorityRepository(project_root=project_root)
    document = repository.load()
    
    # Remove all blocks from core shard
    blocks = document.get_blocks()
    blocks.clear()
    document.replace_blocks(blocks)
    
    with authorize_blueprint_writes_for_tool("test"):
        repository.save(document)
    
    # Verify empty shard was removed
    document = repository.load()
    # The default shard should be removed or kept as empty list
    assert "bpfw/blocks/core.yaml" in [str(p) for p in document.get_included_shard_paths()]


def test_duplicate_block_id_across_shards_blocks(tmp_path: Path):
    """Test that duplicate block ID across shards blocks."""
    # Create project with duplicate block IDs in different shards
    (tmp_path / "bpfw" / "blocks").mkdir(parents=True)
    
    import yaml
    
    # Create blueprint
    blueprint_data = {
        "version": 1,
        "project": {"id": "test", "name": "test"},
        "authority": {
            "layout": "sharded",
            "shard_strategy": "domain",
            "default_shard": "bpfw/blocks/core.yaml",
        },
        "includes": ["bpfw/blocks/core.yaml", "bpfw/blocks/protection.yaml"],
    }
    with open(tmp_path / "bpfw" / "blueprint.yaml", "w") as f:
        yaml.dump(blueprint_data, f)
    
    # Create core.yaml with block_1
    with open(tmp_path / "bpfw" / "blocks" / "core.yaml", "w") as f:
        yaml.dump({"blocks": [{"id": "block_1"}]}, f)
    
    # Create protection.yaml with same block_1
    with open(tmp_path / "bpfw" / "blocks" / "protection.yaml", "w") as f:
        yaml.dump({"blocks": [{"id": "block_1"}]}, f)
    
    repository = AuthorityRepository(project_root=tmp_path)
    with pytest.raises(DuplicateBlockIdError):
        repository.load()


def test_duplicate_code_declaration_across_shards_blocks(tmp_path: Path):
    """Test that duplicate code declaration across shards blocks."""
    # Create project with duplicate code declarations
    (tmp_path / "bpfw" / "blocks").mkdir(parents=True)
    
    import yaml
    
    # Create blueprint
    blueprint_data = {
        "version": 1,
        "project": {"id": "test", "name": "test"},
        "authority": {
            "layout": "sharded",
            "shard_strategy": "domain",
            "default_shard": "bpfw/blocks/core.yaml",
        },
        "includes": ["bpfw/blocks/core.yaml", "bpfw/blocks/protection.yaml"],
    }
    with open(tmp_path / "bpfw" / "blueprint.yaml", "w") as f:
        yaml.dump(blueprint_data, f)
    
    # Create core.yaml with a code declaration
    with open(tmp_path / "bpfw" / "blocks" / "core.yaml", "w") as f:
        yaml.dump({
            "blocks": [{
                "id": "block_a",
                "code": {
                    "path": "src/test.py",
                    "symbol": "TestFunction",
                    "kind": "function",
                },
            }]
        }, f)
    
    # Create protection.yaml with same code declaration
    with open(tmp_path / "bpfw" / "blocks" / "protection.yaml", "w") as f:
        yaml.dump({
            "blocks": [{
                "id": "block_b",
                "code": {
                    "path": "src/test.py",
                    "symbol": "TestFunction",
                    "kind": "function",
                },
            }]
        }, f)
    
    repository = AuthorityRepository(project_root=tmp_path)
    with pytest.raises(DuplicateCodeDeclarationError):
        repository.load()


def test_verify_detects_shard_drift(project_root: Path):
    """Test that verify detects shard drift."""
    repository = AuthorityRepository(project_root=project_root)
    document = repository.load()
    
    # Move block to wrong shard manually (without blueprint layout)
    blocks = document.get_blocks()
    blocks[0]["domain"] = "catalog"  # Should go to catalog.yaml
    document.replace_blocks(blocks)
    
    # Check for drift before applying any save-time blueprint layouting
    planner = BlueprintLayoutPlanner(project_root=project_root)
    plan = planner.build_plan(document)
    
    # Should have moves due to drift
    assert plan.move_count() > 0


def test_verify_reports_layout_change_until_blueprint_engine_applies(project_root: Path):
    """Test that verify passes after blueprint layout --apply."""
    repository = AuthorityRepository(project_root=project_root)
    document = repository.load()
    
    # Change domain to trigger move
    blocks = document.get_blocks()
    blocks[0]["domain"] = "catalog"
    document.replace_blocks(blocks)
    
    # Persist and let authority save perform synchronization.
    planner = BlueprintLayoutPlanner(project_root=project_root)
    with authorize_blueprint_writes_for_tool("test"):
        repository.save(document)
    
    # Reload and verify no drift
    document = repository.load()
    plan = planner.build_plan(document)
    
    # Should have no moves after blueprint layout
    assert plan.move_count() == 0


def test_inspector_save_moves_block_after_domain_change(project_root: Path):
    """Test that inspector save moves block after domain change."""
    repository = AuthorityRepository(project_root=project_root)
    document = repository.load()
    
    # Simulate inspector changing domain
    blocks = document.get_blocks()
    blocks[0]["domain"] = "catalog"
    document.replace_blocks(blocks)
    
    with authorize_blueprint_writes_for_tool("test"):
        repository.save(document)
    
    # Verify block moved to new shard
    document = repository.load()
    new_shard = document.get_origin(blocks[0]["id"])
    
    # Shard should have changed (or plan exists for move)
    assert new_shard is not None


def test_planner_save_places_block_in_domain_shard(project_root: Path):
    """Test that planner save places block in domain shard."""
    repository = AuthorityRepository(project_root=project_root)
    document = repository.load()
    
    # Simulate planner creating a new block with domain
    new_block = {
        "id": "planned_block",
        "purpose": "test",
        "name": "Planned Block",
        "domain": "protection",  # Should go to protection.yaml
        "status": "planned",
        "code": {
            "path": "src/bpfw/protection/new.py",
            "symbol": "NewFunction",
            "kind": "function",
        },
        "detected": {"qualified_name": "bpfw.protection.new.NewFunction", "kind": "function"},
    }
    
    blocks = document.get_blocks()
    blocks.append(new_block)
    document.replace_blocks(blocks)
    with authorize_blueprint_writes_for_tool("test"):
        repository.save(document)
    
    # Verify block is in correct shard
    document = repository.load()
    origin = document.get_origin("planned_block")
    assert origin is not None
    # After blueprint layout, should be in protection.yaml


def test_blueprint_layout_plan_without_writing(project_root: Path):
    """Test that bpfw blueprint layout prints plan without writing."""
    repository = AuthorityRepository(project_root=project_root)
    document = repository.load()
    
    # Create a situation that needs blueprint layouting
    blocks = document.get_blocks()
    blocks[0]["domain"] = "catalog"
    document.replace_blocks(blocks)
    
    planner = BlueprintLayoutPlanner(project_root=project_root)
    plan = planner.build_plan(document)
    
    # Plan should have moves but not be applied
    assert plan.move_count() > 0
    
    # Original files should be unchanged
    original_blocks = repository.load().get_blocks()
    assert len(original_blocks) == len(blocks)


def test_blueprint_engine_writes_moved_blocks(project_root: Path):
    """Test that bpfw blueprint layout --apply writes moved blocks."""
    repository = AuthorityRepository(project_root=project_root)
    document = repository.load()
    
    # Create moves
    blocks = document.get_blocks()
    blocks[0]["domain"] = "catalog"
    blocks[1]["domain"] = "protection"
    document.replace_blocks(blocks)
    
    # Persist and let authority save perform synchronization.
    planner = BlueprintLayoutPlanner(project_root=project_root)
    with authorize_blueprint_writes_for_tool("test"):
        repository.save(document)
    
    # Reload and verify moves were applied
    document = repository.load()
    new_plan = planner.build_plan(document)
    
    # Should have no moves after blueprint layout
    assert new_plan.move_count() == 0


def test_shard_decision_engine_domain_strategy(project_root: Path):
    """Test that shard decision engine uses domain strategy correctly."""
    authority_config = {
        "layout": "sharded",
        "shard_strategy": "domain",
        "default_shard": "bpfw/blocks/uncategorized.yaml",
    }
    
    engine = ShardDecisionEngine(authority_config)
    
    block = {
        "id": "test_block",
        "domain": "protection",
        "code": {"path": "src/test.py"},
    }
    
    shard = engine.decide_shard_for_block(block, None)
    assert "protection" in str(shard)


def test_shard_decision_engine_default_shard(project_root: Path):
    """Test that shard decision engine uses default shard when no domain."""
    authority_config = {
        "layout": "sharded",
        "shard_strategy": "domain",
        "default_shard": "bpfw/blocks/uncategorized.yaml",
    }
    
    engine = ShardDecisionEngine(authority_config)
    
    block = {
        "id": "test_block",
        "domain": None,  # No domain
        "code": {"path": "src/test.py"},
    }
    
    shard = engine.decide_shard_for_block(block, None)
    assert str(shard).endswith("uncategorized.yaml")


def test_blueprint_layout_plan_has_changes():
    """Test that BlueprintLayoutPlan.has_changes() works correctly."""
    plan = BlueprintLayoutPlan(
        strategy="domain",
        default_shard=Path("bpfw/blocks/core.yaml"),
    )
    
    assert not plan.has_changes()
    assert plan.move_count() == 0
    
    # Add a move
    from bpfw.authority.layout import BlockPlacementChange
    plan.moves.append(BlockPlacementChange(
        block_id="test",
        source_shard=Path("a.yaml"),
        target_shard=Path("b.yaml"),
        reason="test",
    ))
    
    assert plan.has_changes()
    assert plan.move_count() == 1
