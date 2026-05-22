"""Tests for the internal authority patch engine.

Covers all patch operations, plan validation, engine apply, rollback,
transaction backup, write context requirements, and read-only command
boundaries.
"""

from pathlib import Path

import pytest
import yaml

from bpfw.core.authority.patch import (
    AuthorityPatchEngine,
    AuthorityPatchPlan,
    PatchWriteContext,
    TransactionBackup,
    CreateBlockOperation,
    CreateShardFileOperation,
    DeleteBlockOperation,
    DeleteShardFileOperation,
    MoveBlockOperation,
    MoveShardFileOperation,
    PatchOperationKind,
    RenameShardFileOperation,
    UpdateBlockMetadataOperation,
)
from bpfw.core.authority.errors import AuthorityError
from bpfw.core.catalog.access_control import authorize_blueprint_writes_for_tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_project_manifest(
    project_root: Path,
    includes: list[str] | None = None,
) -> None:
    """Write a minimal sharded blueprint manifest."""
    blueprint_path = project_root / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "version": 1,
        "project": {
            "id": "test_project",
            "name": "test-project",
            "source_roots": ["src"],
        },
        "authority": {
            "layout": "sharded",
            "shard_strategy": "domain",
            "default_shard": "bpfw/blocks/core.yaml",
        },
    }
    if includes is not None:
        manifest["includes"] = includes
    blueprint_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )


def _write_shard(
    project_root: Path,
    relative_path: str,
    blocks: list[dict],
) -> Path:
    """Write a shard YAML file and return its absolute path."""
    shard_path = project_root / relative_path
    shard_path.parent.mkdir(parents=True, exist_ok=True)
    shard_path.write_text(
        yaml.safe_dump({"blocks": blocks}, sort_keys=False),
        encoding="utf-8",
    )
    return shard_path


def _sample_block(block_id: str = "block_a") -> dict:
    """Return a minimal valid authority block."""
    return {
        "id": block_id,
        "name": block_id,
        "purpose": f"purpose of {block_id}",
        "domain": "test_domain",
        "status": "active",
    }


def _make_engine(project_root: Path) -> AuthorityPatchEngine:
    """Create an engine for the given project root."""
    return AuthorityPatchEngine(project_root=project_root)


def _valid_write_context() -> PatchWriteContext:
    """Return a valid write context for tests."""
    return PatchWriteContext(tool_name="test", allow_guarded_writes=True)


# ---------------------------------------------------------------------------
# PatchWriteContext
# ---------------------------------------------------------------------------

class TestPatchWriteContext:

    def test_valid_context(self) -> None:
        context = PatchWriteContext(tool_name="diff")
        assert context.is_valid()

    def test_empty_tool_name_is_invalid(self) -> None:
        context = PatchWriteContext(tool_name="")
        assert not context.is_valid()

    def test_whitespace_tool_name_is_invalid(self) -> None:
        context = PatchWriteContext(tool_name="   ")
        assert not context.is_valid()


# ---------------------------------------------------------------------------
# TransactionBackup
# ---------------------------------------------------------------------------

class TestTransactionBackup:

    def test_backup_and_rollback_restores_file(self, tmp_path: Path) -> None:
        relative = Path("bpfw/blocks/core.yaml")
        absolute = tmp_path / relative
        absolute.parent.mkdir(parents=True)
        absolute.write_text("original content", encoding="utf-8")

        backup = TransactionBackup(tmp_path)
        backup.backup(relative)

        absolute.write_text("modified content", encoding="utf-8")
        restored = backup.rollback()

        assert relative in restored
        assert absolute.read_text(encoding="utf-8") == "original content"

    def test_rollback_removes_newly_created_file(self, tmp_path: Path) -> None:
        relative = Path("bpfw/blocks/new.yaml")

        backup = TransactionBackup(tmp_path)
        backup.backup(relative)

        absolute = tmp_path / relative
        absolute.parent.mkdir(parents=True)
        absolute.write_text("new file", encoding="utf-8")

        restored = backup.rollback()
        assert relative in restored
        assert not absolute.exists()

    def test_commit_cleans_up_backup_dir(self, tmp_path: Path) -> None:
        relative = Path("bpfw/blocks/core.yaml")
        absolute = tmp_path / relative
        absolute.parent.mkdir(parents=True)
        absolute.write_text("content", encoding="utf-8")

        backup = TransactionBackup(tmp_path)
        backup.backup(relative)
        assert backup.backup_dir.exists()

        backup.commit()
        assert not backup.backup_dir.exists()


# ---------------------------------------------------------------------------
# AuthorityPatchPlan
# ---------------------------------------------------------------------------

class TestAuthorityPatchPlan:

    def test_empty_plan(self) -> None:
        plan = AuthorityPatchPlan()
        assert plan.is_empty()
        assert plan.operation_count() == 0

    def test_add_operation(self) -> None:
        plan = AuthorityPatchPlan()
        operation = MoveBlockOperation(
            block_id="block_a",
            source_shard_path=Path("bpfw/blocks/source.yaml"),
            target_shard_path=Path("bpfw/blocks/target.yaml"),
        )
        plan.add_operation(operation)
        assert not plan.is_empty()
        assert plan.operation_count() == 1

    def test_affected_files(self) -> None:
        plan = AuthorityPatchPlan()
        plan.add_operation(
            MoveBlockOperation(
                block_id="block_a",
                source_shard_path=Path("bpfw/blocks/source.yaml"),
                target_shard_path=Path("bpfw/blocks/target.yaml"),
            )
        )
        affected = plan.affected_files()
        assert Path("bpfw/blocks/source.yaml") in affected
        assert Path("bpfw/blocks/target.yaml") in affected

    def test_requires_manifest_update(self) -> None:
        plan = AuthorityPatchPlan()
        plan.add_operation(
            CreateShardFileOperation(shard_path=Path("bpfw/blocks/new.yaml"))
        )
        assert plan.requires_manifest_update()

    def test_sorted_operations_order(self) -> None:
        plan = AuthorityPatchPlan()
        # Add in reverse order
        plan.add_operation(
            DeleteBlockOperation(
                block_id="block_a",
                source_shard_path=Path("bpfw/blocks/core.yaml"),
            )
        )
        plan.add_operation(
            CreateShardFileOperation(shard_path=Path("bpfw/blocks/new.yaml"))
        )
        plan.add_operation(
            MoveBlockOperation(
                block_id="block_a",
                source_shard_path=Path("bpfw/blocks/source.yaml"),
                target_shard_path=Path("bpfw/blocks/target.yaml"),
            )
        )

        sorted_ops = plan.sorted_operations()
        kinds = [op.kind for op in sorted_ops]
        assert kinds.index(PatchOperationKind.CREATE_SHARD_FILE) < kinds.index(
            PatchOperationKind.MOVE_BLOCK
        )
        assert kinds.index(PatchOperationKind.MOVE_BLOCK) < kinds.index(
            PatchOperationKind.DELETE_BLOCK
        )


# ---------------------------------------------------------------------------
# Patch Operations - Validation
# ---------------------------------------------------------------------------

class TestMoveBlockOperationValidation:

    def test_fails_if_source_does_not_exist(self, tmp_path: Path) -> None:
        operation = MoveBlockOperation(
            block_id="block_a",
            source_shard_path=Path("bpfw/blocks/missing.yaml"),
            target_shard_path=Path("bpfw/blocks/target.yaml"),
        )
        with pytest.raises(AuthorityError, match="Source shard"):
            operation.validate(tmp_path)

    def test_fails_if_block_not_in_source(self, tmp_path: Path) -> None:
        _write_shard(tmp_path, "bpfw/blocks/source.yaml", [_sample_block("other_block")])
        operation = MoveBlockOperation(
            block_id="block_a",
            source_shard_path=Path("bpfw/blocks/source.yaml"),
            target_shard_path=Path("bpfw/blocks/target.yaml"),
        )
        with pytest.raises(AuthorityError, match="not found"):
            operation.validate(tmp_path)

    def test_validates_successfully(self, tmp_path: Path) -> None:
        _write_shard(tmp_path, "bpfw/blocks/source.yaml", [_sample_block("block_a")])
        operation = MoveBlockOperation(
            block_id="block_a",
            source_shard_path=Path("bpfw/blocks/source.yaml"),
            target_shard_path=Path("bpfw/blocks/target.yaml"),
            create_target_if_missing=True,
        )
        operation.validate(tmp_path)  # Should not raise


class TestCreateBlockOperationValidation:

    def test_fails_if_block_missing_id(self, tmp_path: Path) -> None:
        _write_shard(tmp_path, "bpfw/blocks/core.yaml", [])
        operation = CreateBlockOperation(
            block_data={"name": "no_id"},
            target_shard_path=Path("bpfw/blocks/core.yaml"),
        )
        with pytest.raises(AuthorityError, match="id"):
            operation.validate(tmp_path)

    def test_fails_on_duplicate_block_id(self, tmp_path: Path) -> None:
        _write_shard(tmp_path, "bpfw/blocks/core.yaml", [_sample_block("block_a")])
        operation = CreateBlockOperation(
            block_data=_sample_block("block_a"),
            target_shard_path=Path("bpfw/blocks/core.yaml"),
        )
        with pytest.raises(AuthorityError, match="already contains"):
            operation.validate(tmp_path)


class TestDeleteBlockOperationValidation:

    def test_fails_if_source_missing(self, tmp_path: Path) -> None:
        operation = DeleteBlockOperation(
            block_id="block_a",
            source_shard_path=Path("bpfw/blocks/missing.yaml"),
        )
        with pytest.raises(AuthorityError):
            operation.validate(tmp_path)

    def test_fails_if_block_not_in_shard(self, tmp_path: Path) -> None:
        _write_shard(tmp_path, "bpfw/blocks/core.yaml", [_sample_block("other")])
        operation = DeleteBlockOperation(
            block_id="block_a",
            source_shard_path=Path("bpfw/blocks/core.yaml"),
        )
        with pytest.raises(AuthorityError, match="not found"):
            operation.validate(tmp_path)


class TestUpdateBlockMetadataOperationValidation:

    def test_fails_for_disallowed_field(self, tmp_path: Path) -> None:
        _write_shard(tmp_path, "bpfw/blocks/core.yaml", [_sample_block("block_a")])
        operation = UpdateBlockMetadataOperation(
            block_id="block_a",
            source_shard_path=Path("bpfw/blocks/core.yaml"),
            metadata_changes={"forbidden_field": "value"},
        )
        with pytest.raises(AuthorityError, match="not allowed"):
            operation.validate(tmp_path)

    def test_fails_if_block_not_found(self, tmp_path: Path) -> None:
        _write_shard(tmp_path, "bpfw/blocks/core.yaml", [_sample_block("other")])
        operation = UpdateBlockMetadataOperation(
            block_id="block_a",
            source_shard_path=Path("bpfw/blocks/core.yaml"),
            metadata_changes={"purpose": "new purpose"},
        )
        with pytest.raises(AuthorityError, match="not found"):
            operation.validate(tmp_path)


class TestCreateShardFileOperationValidation:

    def test_fails_if_file_already_exists(self, tmp_path: Path) -> None:
        _write_shard(tmp_path, "bpfw/blocks/existing.yaml", [])
        operation = CreateShardFileOperation(
            shard_path=Path("bpfw/blocks/existing.yaml"),
        )
        with pytest.raises(AuthorityError, match="already exists"):
            operation.validate(tmp_path)

    def test_fails_for_path_outside_authority(self, tmp_path: Path) -> None:
        operation = CreateShardFileOperation(
            shard_path=Path("src/blocks/outside.yaml"),
        )
        with pytest.raises(AuthorityError):
            operation.validate(tmp_path)


class TestDeleteShardFileOperationValidation:

    def test_fails_if_file_does_not_exist(self, tmp_path: Path) -> None:
        operation = DeleteShardFileOperation(
            shard_path=Path("bpfw/blocks/missing.yaml"),
        )
        with pytest.raises(AuthorityError):
            operation.validate(tmp_path)

    def test_fails_if_require_empty_and_shard_has_blocks(self, tmp_path: Path) -> None:
        _write_shard(tmp_path, "bpfw/blocks/core.yaml", [_sample_block()])
        operation = DeleteShardFileOperation(
            shard_path=Path("bpfw/blocks/core.yaml"),
            require_empty=True,
        )
        with pytest.raises(AuthorityError, match="non-empty"):
            operation.validate(tmp_path)


class TestRenameShardFileOperationValidation:

    def test_fails_if_source_does_not_exist(self, tmp_path: Path) -> None:
        operation = RenameShardFileOperation(
            source_shard_path=Path("bpfw/blocks/missing.yaml"),
            target_shard_path=Path("bpfw/blocks/renamed.yaml"),
        )
        with pytest.raises(AuthorityError):
            operation.validate(tmp_path)

    def test_fails_if_target_already_exists(self, tmp_path: Path) -> None:
        _write_shard(tmp_path, "bpfw/blocks/source.yaml", [])
        _write_shard(tmp_path, "bpfw/blocks/target.yaml", [])
        operation = RenameShardFileOperation(
            source_shard_path=Path("bpfw/blocks/source.yaml"),
            target_shard_path=Path("bpfw/blocks/target.yaml"),
        )
        with pytest.raises(AuthorityError, match="already exists"):
            operation.validate(tmp_path)


# ---------------------------------------------------------------------------
# Engine Apply - Block Operations
# ---------------------------------------------------------------------------

class TestEngineMoveBlock:

    def test_moves_block_between_shards(self, tmp_path: Path) -> None:
        _write_project_manifest(tmp_path, includes=["bpfw/blocks/source.yaml"])
        _write_shard(tmp_path, "bpfw/blocks/source.yaml", [_sample_block("block_a")])
        _write_shard(tmp_path, "bpfw/blocks/target.yaml", [])

        plan = AuthorityPatchPlan()
        plan.add_operation(
            MoveBlockOperation(
                block_id="block_a",
                source_shard_path=Path("bpfw/blocks/source.yaml"),
                target_shard_path=Path("bpfw/blocks/target.yaml"),
            )
        )

        engine = _make_engine(tmp_path)
        with authorize_blueprint_writes_for_tool("test"):
            result = engine.apply(plan, _valid_write_context())

        assert result.success
        assert "move_block" in result.applied_operations

        target_data = yaml.safe_load(
            (tmp_path / "bpfw/blocks/target.yaml").read_text(encoding="utf-8")
        )
        block_ids = [block["id"] for block in target_data["blocks"]]
        assert "block_a" in block_ids

    def test_creates_target_if_missing(self, tmp_path: Path) -> None:
        _write_project_manifest(tmp_path, includes=["bpfw/blocks/source.yaml"])
        _write_shard(tmp_path, "bpfw/blocks/source.yaml", [_sample_block("block_a")])

        plan = AuthorityPatchPlan()
        plan.add_operation(
            MoveBlockOperation(
                block_id="block_a",
                source_shard_path=Path("bpfw/blocks/source.yaml"),
                target_shard_path=Path("bpfw/blocks/new_target.yaml"),
                create_target_if_missing=True,
            )
        )

        engine = _make_engine(tmp_path)
        with authorize_blueprint_writes_for_tool("test"):
            result = engine.apply(plan, _valid_write_context())

        assert result.success
        assert (tmp_path / "bpfw/blocks/new_target.yaml").exists()

    def test_skips_if_block_not_found(self, tmp_path: Path) -> None:
        _write_project_manifest(tmp_path)
        _write_shard(tmp_path, "bpfw/blocks/source.yaml", [_sample_block("other")])
        _write_shard(tmp_path, "bpfw/blocks/target.yaml", [])

        plan = AuthorityPatchPlan()
        plan.add_operation(
            MoveBlockOperation(
                block_id="block_a",
                source_shard_path=Path("bpfw/blocks/source.yaml"),
                target_shard_path=Path("bpfw/blocks/target.yaml"),
            )
        )

        engine = _make_engine(tmp_path)
        with authorize_blueprint_writes_for_tool("test"):
            result = engine.apply(plan, _valid_write_context())

        # Should fail validation before apply
        assert not result.success


class TestEngineCreateBlock:

    def test_creates_block_in_existing_shard(self, tmp_path: Path) -> None:
        _write_project_manifest(tmp_path)
        _write_shard(tmp_path, "bpfw/blocks/core.yaml", [])

        plan = AuthorityPatchPlan()
        plan.add_operation(
            CreateBlockOperation(
                block_data=_sample_block("new_block"),
                target_shard_path=Path("bpfw/blocks/core.yaml"),
            )
        )

        engine = _make_engine(tmp_path)
        with authorize_blueprint_writes_for_tool("test"):
            result = engine.apply(plan, _valid_write_context())

        assert result.success
        shard_data = yaml.safe_load(
            (tmp_path / "bpfw/blocks/core.yaml").read_text(encoding="utf-8")
        )
        block_ids = [block["id"] for block in shard_data["blocks"]]
        assert "new_block" in block_ids


class TestEngineDeleteBlock:

    def test_deletes_block_from_shard(self, tmp_path: Path) -> None:
        _write_project_manifest(tmp_path)
        _write_shard(
            tmp_path,
            "bpfw/blocks/core.yaml",
            [_sample_block("block_a"), _sample_block("block_b")],
        )

        plan = AuthorityPatchPlan()
        plan.add_operation(
            DeleteBlockOperation(
                block_id="block_a",
                source_shard_path=Path("bpfw/blocks/core.yaml"),
            )
        )

        engine = _make_engine(tmp_path)
        with authorize_blueprint_writes_for_tool("test"):
            result = engine.apply(plan, _valid_write_context())

        assert result.success
        shard_data = yaml.safe_load(
            (tmp_path / "bpfw/blocks/core.yaml").read_text(encoding="utf-8")
        )
        block_ids = [block["id"] for block in shard_data["blocks"]]
        assert "block_a" not in block_ids
        assert "block_b" in block_ids

    def test_does_not_delete_shard_file(self, tmp_path: Path) -> None:
        _write_project_manifest(tmp_path)
        _write_shard(tmp_path, "bpfw/blocks/core.yaml", [_sample_block("block_a")])

        plan = AuthorityPatchPlan()
        plan.add_operation(
            DeleteBlockOperation(
                block_id="block_a",
                source_shard_path=Path("bpfw/blocks/core.yaml"),
            )
        )

        engine = _make_engine(tmp_path)
        with authorize_blueprint_writes_for_tool("test"):
            result = engine.apply(plan, _valid_write_context())

        assert result.success
        # Shard file must still exist (just empty)
        assert (tmp_path / "bpfw/blocks/core.yaml").exists()


class TestEngineUpdateBlockMetadata:

    def test_updates_specified_fields_only(self, tmp_path: Path) -> None:
        _write_project_manifest(tmp_path)
        _write_shard(tmp_path, "bpfw/blocks/core.yaml", [_sample_block("block_a")])

        plan = AuthorityPatchPlan()
        plan.add_operation(
            UpdateBlockMetadataOperation(
                block_id="block_a",
                source_shard_path=Path("bpfw/blocks/core.yaml"),
                metadata_changes={"purpose": "updated purpose"},
            )
        )

        engine = _make_engine(tmp_path)
        with authorize_blueprint_writes_for_tool("test"):
            result = engine.apply(plan, _valid_write_context())

        assert result.success
        shard_data = yaml.safe_load(
            (tmp_path / "bpfw/blocks/core.yaml").read_text(encoding="utf-8")
        )
        block = shard_data["blocks"][0]
        assert block["purpose"] == "updated purpose"
        # Other fields must remain unchanged
        assert block["name"] == "block_a"
        assert block["domain"] == "test_domain"


# ---------------------------------------------------------------------------
# Engine Apply - Shard File Operations
# ---------------------------------------------------------------------------

class TestEngineCreateShardFile:

    def test_creates_new_shard_file(self, tmp_path: Path) -> None:
        _write_project_manifest(tmp_path, includes=["bpfw/blocks/core.yaml"])

        plan = AuthorityPatchPlan()
        plan.add_operation(
            CreateShardFileOperation(
                shard_path=Path("bpfw/blocks/new_domain.yaml"),
                initial_blocks=[_sample_block("block_a")],
            )
        )

        engine = _make_engine(tmp_path)
        with authorize_blueprint_writes_for_tool("test"):
            result = engine.apply(plan, _valid_write_context())

        assert result.success
        new_shard = tmp_path / "bpfw/blocks/new_domain.yaml"
        assert new_shard.exists()
        data = yaml.safe_load(new_shard.read_text(encoding="utf-8"))
        assert len(data["blocks"]) == 1


class TestEngineDeleteShardFile:

    def test_deletes_empty_shard(self, tmp_path: Path) -> None:
        _write_project_manifest(
            tmp_path, includes=["bpfw/blocks/core.yaml", "bpfw/blocks/empty.yaml"]
        )
        _write_shard(tmp_path, "bpfw/blocks/empty.yaml", [])

        plan = AuthorityPatchPlan()
        plan.add_operation(
            DeleteShardFileOperation(
                shard_path=Path("bpfw/blocks/empty.yaml"),
                require_empty=True,
            )
        )

        engine = _make_engine(tmp_path)
        with authorize_blueprint_writes_for_tool("test"):
            result = engine.apply(plan, _valid_write_context())

        assert result.success
        assert not (tmp_path / "bpfw/blocks/empty.yaml").exists()


class TestEngineRenameShardFile:

    def test_renames_shard_file(self, tmp_path: Path) -> None:
        _write_project_manifest(
            tmp_path, includes=["bpfw/blocks/original.yaml"]
        )
        _write_shard(tmp_path, "bpfw/blocks/original.yaml", [_sample_block()])

        plan = AuthorityPatchPlan()
        plan.add_operation(
            RenameShardFileOperation(
                source_shard_path=Path("bpfw/blocks/original.yaml"),
                target_shard_path=Path("bpfw/blocks/renamed.yaml"),
            )
        )

        engine = _make_engine(tmp_path)
        with authorize_blueprint_writes_for_tool("test"):
            result = engine.apply(plan, _valid_write_context())

        assert result.success
        assert not (tmp_path / "bpfw/blocks/original.yaml").exists()
        assert (tmp_path / "bpfw/blocks/renamed.yaml").exists()

    def test_refuses_overwrite(self, tmp_path: Path) -> None:
        _write_shard(tmp_path, "bpfw/blocks/source.yaml", [])
        _write_shard(tmp_path, "bpfw/blocks/existing.yaml", [])

        plan = AuthorityPatchPlan()
        plan.add_operation(
            RenameShardFileOperation(
                source_shard_path=Path("bpfw/blocks/source.yaml"),
                target_shard_path=Path("bpfw/blocks/existing.yaml"),
            )
        )

        engine = _make_engine(tmp_path)
        result = engine.apply(plan, _valid_write_context())
        assert not result.success


class TestEngineMoveShardFile:

    def test_moves_shard_to_subdirectory(self, tmp_path: Path) -> None:
        _write_project_manifest(
            tmp_path, includes=["bpfw/blocks/core.yaml"]
        )
        _write_shard(tmp_path, "bpfw/blocks/core.yaml", [_sample_block()])

        plan = AuthorityPatchPlan()
        plan.add_operation(
            MoveShardFileOperation(
                source_shard_path=Path("bpfw/blocks/core.yaml"),
                target_shard_path=Path("bpfw/blocks/sub/moved.yaml"),
            )
        )

        engine = _make_engine(tmp_path)
        with authorize_blueprint_writes_for_tool("test"):
            result = engine.apply(plan, _valid_write_context())

        assert result.success
        assert not (tmp_path / "bpfw/blocks/core.yaml").exists()
        assert (tmp_path / "bpfw/blocks/sub/moved.yaml").exists()


# ---------------------------------------------------------------------------
# Engine - Write Context and Permission
# ---------------------------------------------------------------------------

class TestEngineWriteContext:

    def test_refuses_empty_plan(self, tmp_path: Path) -> None:
        engine = _make_engine(tmp_path)
        result = engine.apply(AuthorityPatchPlan(), _valid_write_context())
        assert result.success  # Empty plan is "successful" (nothing to do)
        assert "Plan is empty" in result.messages[0]

    def test_requires_valid_write_context(self, tmp_path: Path) -> None:
        _write_project_manifest(tmp_path)
        plan = AuthorityPatchPlan()
        plan.add_operation(
            CreateShardFileOperation(shard_path=Path("bpfw/blocks/new.yaml"))
        )
        engine = _make_engine(tmp_path)
        result = engine.apply(plan, PatchWriteContext(tool_name=""))
        assert not result.success
        assert result.error_message is not None
        assert "Invalid write context" in result.error_message

    def test_fails_on_validation_errors(self, tmp_path: Path) -> None:
        plan = AuthorityPatchPlan()
        plan.add_operation(
            MoveBlockOperation(
                block_id="nonexistent",
                source_shard_path=Path("bpfw/blocks/missing.yaml"),
                target_shard_path=Path("bpfw/blocks/target.yaml"),
            )
        )
        engine = _make_engine(tmp_path)
        result = engine.apply(plan, _valid_write_context())
        assert not result.success
        assert result.error_message is not None
        assert "validation failed" in result.error_message


# ---------------------------------------------------------------------------
# Engine - Preview
# ---------------------------------------------------------------------------

class TestEnginePreview:

    def test_preview_does_not_write_files(self, tmp_path: Path) -> None:
        _write_project_manifest(tmp_path)
        _write_shard(tmp_path, "bpfw/blocks/core.yaml", [_sample_block()])

        plan = AuthorityPatchPlan()
        plan.add_operation(
            DeleteBlockOperation(
                block_id="block_a",
                source_shard_path=Path("bpfw/blocks/core.yaml"),
            )
        )

        engine = _make_engine(tmp_path)
        result = engine.preview(plan)

        # File must not be modified
        shard_data = yaml.safe_load(
            (tmp_path / "bpfw/blocks/core.yaml").read_text(encoding="utf-8")
        )
        assert len(shard_data["blocks"]) == 1
        assert any("Would modify" in message for message in result.messages)


# ---------------------------------------------------------------------------
# Engine - Manifest Update
# ---------------------------------------------------------------------------

class TestEngineManifestUpdate:

    def test_adds_include_on_create_shard(self, tmp_path: Path) -> None:
        _write_project_manifest(tmp_path, includes=["bpfw/blocks/core.yaml"])

        plan = AuthorityPatchPlan()
        plan.add_operation(
            CreateShardFileOperation(
                shard_path=Path("bpfw/blocks/new_domain.yaml"),
            )
        )

        engine = _make_engine(tmp_path)
        with authorize_blueprint_writes_for_tool("test"):
            result = engine.apply(plan, _valid_write_context())

        assert result.success
        assert result.manifest_updated
        manifest = yaml.safe_load(
            (tmp_path / "bpfw/blueprint.yaml").read_text(encoding="utf-8")
        )
        assert "bpfw/blocks/new_domain.yaml" in manifest["includes"]

    def test_removes_include_on_delete_shard(self, tmp_path: Path) -> None:
        _write_project_manifest(
            tmp_path,
            includes=["bpfw/blocks/core.yaml", "bpfw/blocks/deleteme.yaml"],
        )
        _write_shard(tmp_path, "bpfw/blocks/deleteme.yaml", [])

        plan = AuthorityPatchPlan()
        plan.add_operation(
            DeleteShardFileOperation(
                shard_path=Path("bpfw/blocks/deleteme.yaml"),
            )
        )

        engine = _make_engine(tmp_path)
        with authorize_blueprint_writes_for_tool("test"):
            result = engine.apply(plan, _valid_write_context())

        assert result.success
        manifest = yaml.safe_load(
            (tmp_path / "bpfw/blueprint.yaml").read_text(encoding="utf-8")
        )
        assert "bpfw/blocks/deleteme.yaml" not in manifest["includes"]


# ---------------------------------------------------------------------------
# Read-only Command Boundaries
# ---------------------------------------------------------------------------

class TestReadOnlyCommandBoundaries:

    def test_verify_does_not_call_patch_engine(self, tmp_path: Path) -> None:
        """Verify must not import or use the patch engine."""
        import bpfw.core.catalog.verify as verify_module

        source_code = open(verify_module.__file__, encoding="utf-8").read()
        assert "patch_engine" not in source_code
        assert "AuthorityPatchEngine" not in source_code

    def test_status_does_not_call_patch_engine(self, tmp_path: Path) -> None:
        """Status must not import or use the patch engine."""
        import bpfw.reports.status_report as status_module

        source_code = open(status_module.__file__, encoding="utf-8").read()
        assert "patch_engine" not in source_code
        assert "AuthorityPatchEngine" not in source_code

    def test_watch_does_not_call_patch_engine(self, tmp_path: Path) -> None:
        """Watch must not import or use the patch engine."""
        import bpfw.watch as watch_module

        source_code = open(watch_module.__file__, encoding="utf-8").read()
        assert "patch_engine" not in source_code
        assert "AuthorityPatchEngine" not in source_code

    def test_cli_does_not_expose_blueprint_engine_mutation_path(self) -> None:
        """CLI must not route public commands directly to the patch engine."""
        import bpfw.cli as cli_module

        source_code = open(cli_module.__file__, encoding="utf-8").read()
        assert "AuthorityPatchEngine" not in source_code
        assert "bpfw.core.blueprint_engine" not in source_code


# ---------------------------------------------------------------------------
# Deterministic Apply Order
# ---------------------------------------------------------------------------

class TestDeterministicApplyOrder:

    def test_create_shard_before_block_operations(self, tmp_path: Path) -> None:
        """CreateShardFile must run before MoveBlock that targets it."""
        _write_project_manifest(tmp_path)
        _write_shard(tmp_path, "bpfw/blocks/source.yaml", [_sample_block("block_a")])

        plan = AuthorityPatchPlan()
        # Add move first, create second - engine must reorder
        plan.add_operation(
            MoveBlockOperation(
                block_id="block_a",
                source_shard_path=Path("bpfw/blocks/source.yaml"),
                target_shard_path=Path("bpfw/blocks/new_shard.yaml"),
                create_target_if_missing=False,
            )
        )
        plan.add_operation(
            CreateShardFileOperation(
                shard_path=Path("bpfw/blocks/new_shard.yaml"),
            )
        )

        sorted_ops = plan.sorted_operations()
        kinds = [op.kind for op in sorted_ops]
        assert kinds[0] == PatchOperationKind.CREATE_SHARD_FILE
        assert kinds[1] == PatchOperationKind.MOVE_BLOCK