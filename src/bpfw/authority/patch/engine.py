"""Internal authority patch engine for BPFW.

Applies an ``AuthorityPatchPlan`` safely with validation, backups,
rollback, and structured results. This engine is not part of the
public CLI and must not be invoked from read-only commands.
"""

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import yaml

from bpfw.authority.patch.actions import (
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
from bpfw.authority.patch.plan import AuthorityPatchPlan, PatchOperation
from bpfw.authority.patch.result import AuthorityPatchResult
from bpfw.authority.patch.transaction import PatchWriteContext, TransactionBackup
from bpfw.catalog.access_control import (
    authorize_blueprint_writes_for_tool,
    authorize_temporary_blueprint_unlock_for_tool,
)
from bpfw.protection.authority import (
    lock_authority,
    unlock_authority,
)


class AuthorityPatchEngine:
    """Apply an ``AuthorityPatchPlan`` safely to authority files.

    The engine:
    1. Validates the plan.
    2. Computes affected files.
    3. Verifies the write context grants permission.
    4. Creates backups of affected files.
    5. Applies operations in deterministic order.
    6. Validates resulting YAML.
    7. Updates the manifest when required.
    8. Returns a structured ``AuthorityPatchResult``.

    On failure the engine attempts rollback from backups.

    Usage::

        engine = AuthorityPatchEngine(project_root=Path("."))
        result = engine.apply(plan, write_context=PatchWriteContext(tool_name="diff"))
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize the engine.

        Args:
            project_root: The project root directory containing
                ``bpfw/`` authority files.
        """
        self.project_root = project_root

    def preview(self, plan: AuthorityPatchPlan) -> AuthorityPatchResult:
        """Preview what the plan would affect without writing files.

        Args:
            plan: The plan to preview.

        Returns:
            Result with ``affected_files`` populated but no writes
            performed.
        """
        result = AuthorityPatchResult()
        if plan.is_empty():
            result.messages.append("Plan is empty. Nothing to preview.")
            return result

        validation_errors = plan.validate(self.project_root)
        if validation_errors:
            for error_message in validation_errors:
                result.messages.append(f"Validation: {error_message}")
            return result

        for relative_path in sorted(plan.affected_files()):
            result.messages.append(f"Would modify: {relative_path}")

        result.modified_files = sorted(plan.affected_files())
        return result

    def apply(
        self,
        plan: AuthorityPatchPlan,
        write_context: PatchWriteContext,
    ) -> AuthorityPatchResult:
        """Apply the plan with explicit write permission.

        Args:
            plan: The plan containing operations to apply.
            write_context: Explicit permission context. Must have a valid
                ``tool_name``.

        Returns:
            Structured result describing what was applied, skipped, or
            rolled back.
        """
        result = AuthorityPatchResult()

        # 1. Validate plan is not empty.
        if plan.is_empty():
            result.messages.append("Plan is empty. Nothing to apply.")
            result.success = True
            return result

        # 2. Validate write context.
        if not write_context.is_valid():
            result.error_message = "Invalid write context: tool_name is required."
            return result

        # 3. Validate all operation preconditions.
        validation_errors = plan.validate(self.project_root)
        if validation_errors:
            result.error_message = "Plan validation failed."
            for error_message in validation_errors:
                result.messages.append(error_message)
            return result

        # 4. Collect affected files and create backups.
        affected = plan.affected_files()
        backup = TransactionBackup(self.project_root)

        for relative_path in affected:
            backup.backup(relative_path)

        # 5. Apply within write authorization context.
        with self._write_authorization(write_context):
            try:
                self._apply_sorted_operations(plan, result)
            except (OSError, yaml.YAMLError, ValueError) as apply_error:
                result.error_message = f"Apply failed: {apply_error}"
                restored = backup.rollback()
                result.rolled_back = True
                for restored_path in restored:
                    result.messages.append(f"Rolled back: {restored_path}")
                return result

            # 6. Validate resulting YAML files while still unlocked.
            yaml_errors = self._validate_yaml_files(affected)
            if yaml_errors:
                result.messages.append("YAML validation warning after apply:")
                for yaml_error in yaml_errors:
                    result.messages.append(f"  {yaml_error}")

            # 7. Update manifest if required (while still unlocked).
            if plan.requires_manifest_update():
                self._update_manifest(plan, result)

        # 8. Commit backups (cleanup).
        backup.commit()

        result.success = True
        return result

    def validate_plan(self, plan: AuthorityPatchPlan) -> list[str]:
        """Validate a plan without applying it.

        Args:
            plan: The plan to validate.

        Returns:
            List of error strings. Empty when valid.
        """
        if plan.is_empty():
            return []
        return plan.validate(self.project_root)

    def collect_affected_files(self, plan: AuthorityPatchPlan) -> set[Path]:
        """Return all files the plan would modify.

        Args:
            plan: The plan to inspect.

        Returns:
            Set of project-relative paths.
        """
        return plan.affected_files()

    @contextmanager
    def _write_authorization(self, context: PatchWriteContext) -> Iterator[None]:
        """Set up blueprint write authorization for the apply.

        Args:
            context: Write context specifying the tool name and
                whether guarded writes are allowed.
        """
        with authorize_blueprint_writes_for_tool(context.tool_name):
            if context.allow_guarded_writes:
                with authorize_temporary_blueprint_unlock_for_tool(context.tool_name):
                    try:
                        unlock_authority(self.project_root)
                        yield
                    finally:
                        lock_authority(self.project_root)
            else:
                yield

    def _apply_sorted_operations(
        self,
        plan: AuthorityPatchPlan,
        result: AuthorityPatchResult,
    ) -> None:
        """Apply each operation in deterministic order.

        Args:
            plan: The plan whose sorted operations to apply.
            result: Result object to record outcomes.
        """
        for operation in plan.sorted_operations():
            self._apply_single_operation(operation, result)

    def _apply_single_operation(
        self,
        operation: PatchOperation,
        result: AuthorityPatchResult,
    ) -> None:
        """Dispatch a single operation to the appropriate handler.

        Args:
            operation: The operation to apply.
            result: Result object to record outcomes.
        """
        kind = operation.kind
        label = kind.value

        if kind == PatchOperationKind.MOVE_BLOCK:
            self._apply_move_block(operation, result, label)  # type: ignore[arg-type]
        elif kind == PatchOperationKind.CREATE_BLOCK:
            self._apply_create_block(operation, result, label)  # type: ignore[arg-type]
        elif kind == PatchOperationKind.DELETE_BLOCK:
            self._apply_delete_block(operation, result, label)  # type: ignore[arg-type]
        elif kind == PatchOperationKind.UPDATE_BLOCK_METADATA:
            self._apply_update_metadata(operation, result, label)  # type: ignore[arg-type]
        elif kind == PatchOperationKind.CREATE_SHARD_FILE:
            self._apply_create_shard_file(operation, result, label)  # type: ignore[arg-type]
        elif kind == PatchOperationKind.DELETE_SHARD_FILE:
            self._apply_delete_shard_file(operation, result, label)  # type: ignore[arg-type]
        elif kind == PatchOperationKind.RENAME_SHARD_FILE:
            self._apply_rename_shard_file(operation, result, label)  # type: ignore[arg-type]
        elif kind == PatchOperationKind.MOVE_SHARD_FILE:
            self._apply_move_shard_file(operation, result, label)  # type: ignore[arg-type]

    def _apply_move_block(
        self,
        operation: MoveBlockOperation,
        result: AuthorityPatchResult,
        label: str,
    ) -> None:
        """Move a block from source shard to target shard.

        Args:
            operation: The move operation details.
            result: Result object to record outcomes.
            label: Human-readable operation label.
        """
        from bpfw.authority.shard import AuthorityShard

        source_shard = AuthorityShard.load(
            self.project_root, operation.source_shard_path
        )
        if not source_shard.contains_block_id(operation.block_id):
            result.add_skipped(label, f"block '{operation.block_id}' not found in source")
            return

        block_data = source_shard.remove_block(operation.block_id)
        if block_data is None:
            result.add_skipped(label, f"block '{operation.block_id}' not found in source")
            return

        source_shard.save(self.project_root)
        result.add_modified(operation.source_shard_path)

        target_absolute = self.project_root / operation.target_shard_path
        if not target_absolute.exists() and operation.create_target_if_missing:
            target_absolute.parent.mkdir(parents=True, exist_ok=True)
            target_absolute.write_text(
                yaml.safe_dump({"blocks": []}, sort_keys=False),
                encoding="utf-8",
            )

        target_shard = AuthorityShard.load(
            self.project_root, operation.target_shard_path
        )
        target_shard.add_block(block_data)
        target_shard.save(self.project_root)
        result.add_modified(operation.target_shard_path)
        result.add_applied(label)

    def _apply_create_block(
        self,
        operation: CreateBlockOperation,
        result: AuthorityPatchResult,
        label: str,
    ) -> None:
        """Create a new block in the target shard.

        Args:
            operation: The create operation details.
            result: Result object to record outcomes.
            label: Human-readable operation label.
        """
        from bpfw.authority.shard import AuthorityShard

        target_absolute = self.project_root / operation.target_shard_path
        if not target_absolute.exists() and operation.create_target_if_missing:
            target_absolute.parent.mkdir(parents=True, exist_ok=True)
            target_absolute.write_text(
                yaml.safe_dump({"blocks": []}, sort_keys=False),
                encoding="utf-8",
            )

        target_shard = AuthorityShard.load(
            self.project_root, operation.target_shard_path
        )
        target_shard.add_block(operation.block_data)
        target_shard.save(self.project_root)
        result.add_modified(operation.target_shard_path)
        result.add_applied(label)

    def _apply_delete_block(
        self,
        operation: DeleteBlockOperation,
        result: AuthorityPatchResult,
        label: str,
    ) -> None:
        """Delete a block from the source shard.

        Args:
            operation: The delete operation details.
            result: Result object to record outcomes.
            label: Human-readable operation label.
        """
        from bpfw.authority.shard import AuthorityShard

        source_shard = AuthorityShard.load(
            self.project_root, operation.source_shard_path
        )
        source_shard.remove_block(operation.block_id)
        source_shard.save(self.project_root)
        result.add_modified(operation.source_shard_path)
        result.add_applied(label)

    def _apply_update_metadata(
        self,
        operation: UpdateBlockMetadataOperation,
        result: AuthorityPatchResult,
        label: str,
    ) -> None:
        """Update metadata fields on an existing block.

        Uses ``get_blocks`` and ``set_blocks`` to find and modify the
        target block, since ``AuthorityShard`` does not expose individual
        block accessors.

        Args:
            operation: The metadata update details.
            result: Result object to record outcomes.
            label: Human-readable operation label.
        """
        from bpfw.authority.shard import AuthorityShard

        source_shard = AuthorityShard.load(
            self.project_root, operation.source_shard_path
        )

        blocks = source_shard.get_blocks()
        target_block = None
        for block in blocks:
            if block.get("id") == operation.block_id:
                target_block = block
                break

        if target_block is None:
            result.add_skipped(label, f"block '{operation.block_id}' not found")
            return

        for field_name, field_value in operation.metadata_changes.items():
            target_block[field_name] = field_value

        source_shard.set_blocks(blocks)
        source_shard.save(self.project_root)
        result.add_modified(operation.source_shard_path)
        result.add_applied(label)

    def _apply_create_shard_file(
        self,
        operation: CreateShardFileOperation,
        result: AuthorityPatchResult,
        label: str,
    ) -> None:
        """Create a new shard file.

        Args:
            operation: The shard creation details.
            result: Result object to record outcomes.
            label: Human-readable operation label.
        """
        target_absolute = self.project_root / operation.shard_path
        target_absolute.parent.mkdir(parents=True, exist_ok=True)
        content = {"blocks": operation.initial_blocks}
        target_absolute.write_text(
            yaml.safe_dump(content, sort_keys=False),
            encoding="utf-8",
        )
        result.add_modified(operation.shard_path)
        result.add_applied(label)

    def _apply_delete_shard_file(
        self,
        operation: DeleteShardFileOperation,
        result: AuthorityPatchResult,
        label: str,
    ) -> None:
        """Delete a shard file from disk.

        Args:
            operation: The shard deletion details.
            result: Result object to record outcomes.
            label: Human-readable operation label.
        """
        target_absolute = self.project_root / operation.shard_path
        target_absolute.unlink()
        result.add_modified(operation.shard_path)
        result.add_applied(label)

    def _apply_rename_shard_file(
        self,
        operation: RenameShardFileOperation,
        result: AuthorityPatchResult,
        label: str,
    ) -> None:
        """Rename a shard file.

        Args:
            operation: The rename details.
            result: Result object to record outcomes.
            label: Human-readable operation label.
        """
        source_absolute = self.project_root / operation.source_shard_path
        target_absolute = self.project_root / operation.target_shard_path
        target_absolute.parent.mkdir(parents=True, exist_ok=True)
        source_absolute.rename(target_absolute)
        result.add_modified(operation.source_shard_path)
        result.add_modified(operation.target_shard_path)
        result.add_applied(label)

    def _apply_move_shard_file(
        self,
        operation: MoveShardFileOperation,
        result: AuthorityPatchResult,
        label: str,
    ) -> None:
        """Move a shard file to a new location.

        Args:
            operation: The move details.
            result: Result object to record outcomes.
            label: Human-readable operation label.
        """
        source_absolute = self.project_root / operation.source_shard_path
        target_absolute = self.project_root / operation.target_shard_path
        target_absolute.parent.mkdir(parents=True, exist_ok=True)
        source_absolute.rename(target_absolute)
        result.add_modified(operation.source_shard_path)
        result.add_modified(operation.target_shard_path)
        result.add_applied(label)

    def _validate_yaml_files(self, paths: set[Path]) -> list[str]:
        """Validate that all written files contain valid YAML.

        Args:
            paths: Project-relative paths to validate.

        Returns:
            List of error strings. Empty when all files are valid.
        """
        errors: list[str] = []
        for relative_path in paths:
            absolute_path = self.project_root / relative_path
            if not absolute_path.exists():
                continue
            try:
                raw = absolute_path.read_text(encoding="utf-8")
                yaml.safe_load(raw)
            except yaml.YAMLError as yaml_error:
                errors.append(f"Invalid YAML in {relative_path}: {yaml_error}")
        return errors

    def _update_manifest(
        self,
        plan: AuthorityPatchPlan,
        result: AuthorityPatchResult,
    ) -> None:
        """Update the root manifest includes after shard file changes.

        Only updates if there are create/delete/rename/move shard file
        operations.

        Args:
            plan: The applied plan.
            result: Result object to record the manifest update.
        """
        manifest_path = self.project_root / "bpfw" / "blueprint.yaml"
        if not manifest_path.exists():
            return

        try:
            raw = manifest_path.read_text(encoding="utf-8")
            manifest_data = yaml.safe_load(raw)
        except yaml.YAMLError:
            return

        if not isinstance(manifest_data, dict):
            return

        includes = set(manifest_data.get("includes", []))

        changed = False
        for operation in plan.sorted_operations():
            kind = operation.kind
            if kind == PatchOperationKind.CREATE_SHARD_FILE:
                include_path = str(operation.shard_path)  # type: ignore[union-attr]
                if include_path not in includes:
                    includes.add(include_path)
                    changed = True
            elif kind == PatchOperationKind.DELETE_SHARD_FILE:
                include_path = str(operation.shard_path)  # type: ignore[union-attr]
                if include_path in includes:
                    includes.discard(include_path)
                    changed = True
            elif kind in (
                PatchOperationKind.RENAME_SHARD_FILE,
                PatchOperationKind.MOVE_SHARD_FILE,
            ):
                old_include = str(operation.source_shard_path)  # type: ignore[union-attr]
                new_include = str(operation.target_shard_path)  # type: ignore[union-attr]
                if old_include in includes:
                    includes.discard(old_include)
                    includes.add(new_include)
                    changed = True

        if changed:
            manifest_data["includes"] = sorted(includes)
            manifest_path.write_text(
                yaml.safe_dump(manifest_data, sort_keys=False),
                encoding="utf-8",
            )
            result.manifest_updated = True
            result.add_modified(Path("bpfw/blueprint.yaml"))