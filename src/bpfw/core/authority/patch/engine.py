"""Low-level file-change patch engine used by Blueprint Engine."""

from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

import yaml

from bpfw.core.authority.patch.actions import (
    AddCoveredCodeOperation,
    AddIgnoreRuleOperation,
    CreateBlockOperation,
    CreateShardFileOperation,
    DeleteBlockOperation,
    DeleteShardFileOperation,
    MoveBlockOperation,
    MoveShardFileOperation,
    PatchOperationKind,
    RemoveCoveredCodeOperation,
    RemoveIgnoreRuleOperation,
    RenameShardFileOperation,
    UpdateBlockCodeReferenceOperation,
    UpdateBlockLocationOperation,
    UpdateBlockMetadataOperation,
    UpdateBlockSymbolOperation,
)
from bpfw.core.authority.patch.plan import AuthorityPatchPlan, PatchOperation
from bpfw.core.authority.patch.result import AuthorityPatchResult
from bpfw.core.authority.patch.transaction import (
    AuthorityShardUnitOfWork,
    PatchWriteContext,
    TransactionBackup,
)
from bpfw.core.catalog.access_control import (
    authorize_blueprint_writes_for_tool,
    authorize_temporary_blueprint_unlock_for_tool,
)
from bpfw.core.protection.authority import lock_authority, unlock_authority
from bpfw.core.result import Result, ResultError, ResultStatus, ResultTraceEvent

PatchProgressCallback = Callable[[int, int, str], None]


class AuthorityPatchEngine:
    """Apply an ``AuthorityPatchPlan`` safely to authority files.

    The engine validates, backs up, writes, validates YAML, updates the root
    include list when shard files change, and rolls back on failed filesystem
    operations. It does not build plans and does not decide what authority means.
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize the engine.

        Args:
            project_root: Project root directory containing ``bpfw/``.
        """
        self.project_root = project_root
        self._operation_handlers = self._build_operation_handler_registry()
        self._manifest_include_handlers = self._build_manifest_include_handler_registry()
        self._shard_unit_of_work: AuthorityShardUnitOfWork | None = None

    def _build_operation_handler_registry(self) -> dict[PatchOperationKind, Callable[..., None]]:
        """Build the operation handler registry used by the patch dispatcher.

        Returns:
            Mapping from patch operation kind to the method that applies it.
        """
        return {
            PatchOperationKind.MOVE_BLOCK: self._apply_move_block,
            PatchOperationKind.CREATE_BLOCK: self._apply_create_block,
            PatchOperationKind.DELETE_BLOCK: self._apply_delete_block,
            PatchOperationKind.UPDATE_BLOCK_METADATA: self._apply_update_metadata,
            PatchOperationKind.UPDATE_BLOCK_LOCATION: self._apply_update_location,
            PatchOperationKind.UPDATE_BLOCK_SYMBOL: self._apply_update_symbol,
            PatchOperationKind.UPDATE_BLOCK_CODE_REFERENCE: self._apply_update_code_reference,
            PatchOperationKind.ADD_IGNORE_RULE: self._apply_add_ignore_rule,
            PatchOperationKind.REMOVE_IGNORE_RULE: self._apply_remove_ignore_rule,
            PatchOperationKind.ADD_COVERED_CODE: self._apply_add_covered_code,
            PatchOperationKind.REMOVE_COVERED_CODE: self._apply_remove_covered_code,
            PatchOperationKind.CREATE_SHARD_FILE: self._apply_create_shard_file,
            PatchOperationKind.DELETE_SHARD_FILE: self._apply_delete_shard_file,
            PatchOperationKind.RENAME_SHARD_FILE: self._apply_rename_shard_file,
            PatchOperationKind.MOVE_SHARD_FILE: self._apply_move_shard_file,
        }

    def _build_manifest_include_handler_registry(self) -> dict[PatchOperationKind, Callable[..., bool]]:
        """Build handlers that update manifest includes by operation kind.

        Returns:
            Mapping from patch operation kind to include update function.
        """
        return {
            PatchOperationKind.CREATE_SHARD_FILE: self._include_created_shard,
            PatchOperationKind.CREATE_BLOCK: self._include_target_shard,
            PatchOperationKind.MOVE_BLOCK: self._include_target_shard,
            PatchOperationKind.DELETE_SHARD_FILE: self._remove_deleted_shard_include,
            PatchOperationKind.RENAME_SHARD_FILE: self._replace_moved_shard_include,
            PatchOperationKind.MOVE_SHARD_FILE: self._replace_moved_shard_include,
        }

    def preview(self, plan: AuthorityPatchPlan) -> AuthorityPatchResult:
        """Preview affected files without writing.

        Args:
            plan: Plan to preview.

        Returns:
            Result object containing affected files and validation messages.
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

        affected_files = sorted(plan.affected_files())
        for relative_path in affected_files:
            result.messages.append(f"Would modify: {relative_path}")
        result.modified_files = affected_files
        return result

    def apply(
        self,
        plan: AuthorityPatchPlan,
        write_context: PatchWriteContext,
        progress_callback: PatchProgressCallback | None = None,
    ) -> AuthorityPatchResult:
        """Apply a plan with explicit write permission.

        Args:
            plan: Mechanical patch plan to apply.
            write_context: Explicit permission context for guarded writes.
            progress_callback: Optional callback notified after patch operations progress.

        Returns:
            Structured result describing applied or skipped operations.
        """
        result = AuthorityPatchResult()

        if plan.is_empty():
            result.messages.append("Plan is empty. Nothing to apply.")
            result.success = True
            return result

        if not write_context.is_valid():
            result.error_message = "Invalid write context: tool_name is required."
            return result

        validation_errors = plan.validate(self.project_root)
        if validation_errors:
            result.error_message = "Plan validation failed."
            result.messages.extend(validation_errors)
            return result

        affected_files = plan.affected_files()
        result.add_trace(
            "patch.apply",
            ResultStatus.INFO,
            "Patch plan accepted for transactional apply.",
            {"affected_files": str(len(affected_files))},
        )
        backup = TransactionBackup(self.project_root)
        backup_result = self._prepare_transaction_backup(affected_files, backup)
        result.extend_trace(backup_result.trace_events)
        if backup_result.is_error:
            return self._fail_with_rollback(result, backup, backup_result.unwrap_error())

        with self._write_authorization(write_context):
            operations_result = self._apply_operations_as_result(plan, result, progress_callback)
            result.extend_trace(operations_result.trace_events)
            if operations_result.is_error:
                return self._fail_with_rollback(result, backup, operations_result.unwrap_error())

            if result.skipped_operations:
                skipped_error = ResultError(
                    code="PATCH_OPERATIONS_SKIPPED",
                    message="Apply failed: one or more operations were skipped.",
                    source="patch.apply",
                    details={"skipped_operations": str(len(result.skipped_operations))},
                )
                return self._fail_with_rollback(result, backup, skipped_error)

            yaml_result = self._validate_yaml_files_as_result(affected_files)
            result.extend_trace(yaml_result.trace_events)
            if yaml_result.is_error:
                return self._fail_with_rollback(result, backup, yaml_result.unwrap_error())

            yaml_errors = yaml_result.unwrap()
            if yaml_errors:
                result.messages.append("YAML validation warning after apply:")
                for yaml_error in yaml_errors:
                    result.messages.append(f"  {yaml_error}")

            if plan.requires_manifest_update():
                manifest_result = self._update_manifest_includes_as_result(plan, result)
                result.extend_trace(manifest_result.trace_events)
                if manifest_result.is_error:
                    return self._fail_with_rollback(result, backup, manifest_result.unwrap_error())

        backup.commit()
        result.add_trace("patch.apply", ResultStatus.OK, "Patch transaction committed.")
        result.success = True
        return result

    def _prepare_transaction_backup(
        self,
        affected_files: set[Path],
        backup: TransactionBackup,
    ) -> Result[None, ResultError]:
        """Back up affected files and return a structured operation result.

        Args:
            affected_files: Project-relative files that may be modified.
            backup: Transaction backup manager.

        Returns:
            Successful result when every existing file was backed up, otherwise a
            failed result with diagnostic trace events.
        """
        trace_events = [
            ResultTraceEvent(
                source="patch.backup",
                status=ResultStatus.INFO,
                message="Creating transaction backups for affected files.",
                details={"affected_files": str(len(affected_files))},
            )
        ]
        try:
            for relative_path in affected_files:
                backup.backup(relative_path)
        except OSError as error:
            trace_events.append(
                ResultTraceEvent(
                    source="patch.backup",
                    status=ResultStatus.BLOCK,
                    message="Transaction backup failed.",
                    details={"error_type": type(error).__name__, "error": str(error)},
                )
            )
            return Result.fail(
                ResultError(
                    code="PATCH_BACKUP_FAILED",
                    message=f"Backup failed: {error}",
                    source="patch.backup",
                    details={"error_type": type(error).__name__},
                ),
                trace_events,
            )

        trace_events.append(
            ResultTraceEvent(
                source="patch.backup",
                status=ResultStatus.OK,
                message="Transaction backups completed.",
            )
        )
        return Result.ok(None, trace_events)

    def _apply_operations_as_result(
        self,
        plan: AuthorityPatchPlan,
        result: AuthorityPatchResult,
        progress_callback: PatchProgressCallback | None = None,
    ) -> Result[None, ResultError]:
        """Apply patch operations and convert recoverable failures to Result.

        Args:
            plan: Mechanical patch plan to apply.
            result: Patch result object that records applied operations.
            progress_callback: Optional callback notified after operation progress.

        Returns:
            Successful result when operations complete, otherwise a failed result.
        """
        trace_events = [
            ResultTraceEvent(
                source="patch.operations",
                status=ResultStatus.INFO,
                message="Applying sorted patch operations.",
                details={"operation_count": str(len(plan.operations))},
            )
        ]
        previous_unit_of_work = self._shard_unit_of_work
        unit_of_work = AuthorityShardUnitOfWork(self.project_root)
        self._shard_unit_of_work = unit_of_work
        try:
            self._apply_sorted_operations(plan, result, progress_callback)
            written_shards = unit_of_work.commit()
        except (OSError, yaml.YAMLError, ValueError) as error:
            trace_events.append(
                ResultTraceEvent(
                    source="patch.operations",
                    status=ResultStatus.BLOCK,
                    message="Patch operation failed before transaction commit.",
                    details={"error_type": type(error).__name__, "error": str(error)},
                )
            )
            return Result.fail(
                ResultError(
                    code="PATCH_OPERATION_FAILED",
                    message=f"Apply failed: {error}",
                    source="patch.operations",
                    details={"error_type": type(error).__name__},
                ),
                trace_events,
            )
        finally:
            self._shard_unit_of_work = previous_unit_of_work

        trace_events.append(
            ResultTraceEvent(
                source="patch.operations",
                status=ResultStatus.OK,
                message="Patch operations completed and changed shards were committed.",
                details={"written_shards": str(len(written_shards))},
            )
        )
        return Result.ok(None, trace_events)

    def _fail_with_rollback(
        self,
        result: AuthorityPatchResult,
        backup: TransactionBackup,
        error: ResultError,
    ) -> AuthorityPatchResult:
        """Record a failed patch result and roll back affected files.

        Args:
            result: Patch result to update.
            backup: Transaction backup manager.
            error: Structured recoverable failure.

        Returns:
            Failed patch result with rollback messages and trace events.
        """
        result.error_message = error.message
        result.add_trace(
            error.source,
            ResultStatus.BLOCK,
            error.message,
            error.details,
        )
        try:
            restored_paths = backup.rollback()
        except OSError as rollback_error:
            result.rolled_back = True
            result.messages.append(f"Rollback failed: {rollback_error}")
            result.add_trace(
                "patch.rollback",
                ResultStatus.CRITICAL,
                "Rollback failed after patch error.",
                {"error_type": type(rollback_error).__name__, "error": str(rollback_error)},
            )
            return result

        result.rolled_back = True
        for restored_path in restored_paths:
            result.messages.append(f"Rolled back: {restored_path}")
        result.add_trace(
            "patch.rollback",
            ResultStatus.OK,
            "Rollback completed after patch error.",
            {"restored_paths": str(len(restored_paths))},
        )
        return result

    def _validate_yaml_files_as_result(self, paths: set[Path]) -> Result[list[str], ResultError]:
        """Validate written YAML files and return a structured result.

        Args:
            paths: Project-relative paths to validate.

        Returns:
            Successful result containing YAML warnings, or a failed result when a
            validation file cannot be read.
        """
        trace_events = [
            ResultTraceEvent(
                source="patch.yaml_validation",
                status=ResultStatus.INFO,
                message="Validating written YAML files.",
                details={"candidate_files": str(len(paths))},
            )
        ]
        errors: list[str] = []
        for relative_path in paths:
            if relative_path.suffix not in {".yaml", ".yml"}:
                continue
            absolute_path = self.project_root / relative_path
            if not absolute_path.exists():
                continue
            try:
                yaml.safe_load(absolute_path.read_text(encoding="utf-8"))
            except yaml.YAMLError as yaml_error:
                errors.append(f"Invalid YAML in {relative_path}: {yaml_error}")
            except OSError as error:
                trace_events.append(
                    ResultTraceEvent(
                        source="patch.yaml_validation",
                        status=ResultStatus.BLOCK,
                        message="YAML validation could not read a written file.",
                        details={"path": str(relative_path), "error": str(error)},
                    )
                )
                return Result.fail(
                    ResultError(
                        code="PATCH_YAML_VALIDATION_READ_FAILED",
                        message=f"YAML validation failed while reading {relative_path}: {error}",
                        source="patch.yaml_validation",
                        details={"path": str(relative_path), "error_type": type(error).__name__},
                    ),
                    trace_events,
                )

        trace_events.append(
            ResultTraceEvent(
                source="patch.yaml_validation",
                status=ResultStatus.OK if not errors else ResultStatus.WARNING,
                message="YAML validation completed.",
                details={"warnings": str(len(errors))},
            )
        )
        return Result.ok(errors, trace_events)

    def _update_manifest_includes_as_result(
        self,
        plan: AuthorityPatchPlan,
        result: AuthorityPatchResult,
    ) -> Result[None, ResultError]:
        """Update manifest includes and return a structured result.

        Args:
            plan: Applied patch plan.
            result: Patch result object that records modified files.

        Returns:
            Successful result when manifest update completes, otherwise a failed
            result with diagnostics.
        """
        trace_events = [
            ResultTraceEvent(
                source="patch.manifest",
                status=ResultStatus.INFO,
                message="Updating manifest includes after shard lifecycle changes.",
            )
        ]
        try:
            self._update_manifest_includes(plan, result)
        except (OSError, yaml.YAMLError, ValueError) as error:
            trace_events.append(
                ResultTraceEvent(
                    source="patch.manifest",
                    status=ResultStatus.BLOCK,
                    message="Manifest include update failed.",
                    details={"error_type": type(error).__name__, "error": str(error)},
                )
            )
            return Result.fail(
                ResultError(
                    code="PATCH_MANIFEST_UPDATE_FAILED",
                    message=f"Manifest update failed: {error}",
                    source="patch.manifest",
                    details={"error_type": type(error).__name__},
                ),
                trace_events,
            )

        trace_events.append(
            ResultTraceEvent(
                source="patch.manifest",
                status=ResultStatus.OK,
                message="Manifest include update completed.",
                details={"manifest_updated": str(result.manifest_updated)},
            )
        )
        return Result.ok(None, trace_events)

    def validate_plan(self, plan: AuthorityPatchPlan) -> list[str]:
        """Validate a plan without applying it.

        Args:
            plan: Plan to validate.

        Returns:
            Validation messages, or an empty list when valid.
        """
        if plan.is_empty():
            return []
        return plan.validate(self.project_root)

    @contextmanager
    def _write_authorization(self, context: PatchWriteContext) -> Iterator[None]:
        """Set up blueprint write authorization for the apply.

        Args:
            context: Write context specifying tool name and guarded write policy.
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
        progress_callback: PatchProgressCallback | None = None,
    ) -> None:
        """Apply each operation in stable order."""
        operations = plan.sorted_operations()
        total_operations = len(operations)
        completed_operations = 0
        index = 0

        while index < total_operations:
            operation = operations[index]
            if operation.kind == PatchOperationKind.UPDATE_BLOCK_CODE_REFERENCE:
                update_operations: list[UpdateBlockCodeReferenceOperation] = []
                while (
                    index < total_operations
                    and operations[index].kind == PatchOperationKind.UPDATE_BLOCK_CODE_REFERENCE
                ):
                    update_operations.append(operations[index])  # type: ignore[arg-type]
                    index += 1
                completed_operations = self._apply_update_code_references_batch(
                    operations=update_operations,
                    result=result,
                    completed_operations=completed_operations,
                    total_operations=total_operations,
                    progress_callback=progress_callback,
                )
                continue

            self._apply_single_operation(operation, result)
            completed_operations += 1
            if progress_callback is not None:
                progress_callback(completed_operations, total_operations, operation.kind.value)
            index += 1

    def _apply_update_code_references_batch(
        self,
        operations: list[UpdateBlockCodeReferenceOperation],
        result: AuthorityPatchResult,
        completed_operations: int,
        total_operations: int,
        progress_callback: PatchProgressCallback | None = None,
    ) -> int:
        """Apply code-reference updates grouped by shard.

        Args:
            operations: Code-reference update operations to apply.
            result: Result object to record outcomes.
            completed_operations: Number of already completed operations.
            total_operations: Total operations in the full plan.
            progress_callback: Optional callback notified after each operation.

        Returns:
            Updated completed operation count.
        """
        from collections import defaultdict

        operations_by_shard: dict[Path, list[UpdateBlockCodeReferenceOperation]] = defaultdict(list)
        for operation in operations:
            operations_by_shard[operation.source_shard_path].append(operation)

        label = PatchOperationKind.UPDATE_BLOCK_CODE_REFERENCE.value
        for shard_path, shard_operations in operations_by_shard.items():
            shard = self._load_shard_for_patch(shard_path)
            blocks = shard.get_blocks()
            block_by_id = {
                block.get("id"): block
                for block in blocks
                if isinstance(block, dict) and isinstance(block.get("id"), str)
            }
            shard_changed = False

            for operation in shard_operations:
                block = block_by_id.get(operation.block_id)
                if block is None:
                    result.add_skipped(label, f"block '{operation.block_id}' not found")
                    completed_operations += 1
                    if progress_callback is not None:
                        progress_callback(completed_operations, total_operations, label)
                    continue

                code = block.setdefault("code", {})
                if not isinstance(code, dict):
                    code = {}
                    block["code"] = code
                code["path"] = operation.new_path
                code["symbol"] = operation.new_symbol
                if operation.new_kind is not None:
                    code["kind"] = operation.new_kind
                if operation.new_name is not None:
                    block["name"] = operation.new_name
                shard_changed = True
                result.add_applied(label)
                completed_operations += 1
                if progress_callback is not None:
                    progress_callback(completed_operations, total_operations, label)

            if shard_changed:
                shard.set_blocks(blocks)
                self._mark_shard_changed(shard_path, shard)
                result.add_modified(shard_path)

        return completed_operations

    def _apply_single_operation(
        self,
        operation: PatchOperation,
        result: AuthorityPatchResult,
    ) -> None:
        """Dispatch one operation through the operation handler registry.

        Args:
            operation: Operation to apply.
            result: Result object to record outcomes.
        """
        label = operation.kind.value
        handler = self._operation_handlers.get(operation.kind)
        if handler is None:
            result.add_skipped(label, f"unsupported operation kind: {operation.kind}")
            return
        handler(operation, result, label)

    def _load_shard_for_patch(self, shard_path: Path, create_if_missing: bool = False):  # noqa: ANN201
        """Load a shard through the active unit of work when available.

        Args:
            shard_path: Project-relative shard path.
            create_if_missing: Whether to create an empty in-memory shard when missing.

        Returns:
            Authority shard instance.
        """
        if self._shard_unit_of_work is not None:
            return self._shard_unit_of_work.load_shard(
                shard_path=shard_path,
                create_if_missing=create_if_missing,
            )

        from bpfw.core.authority.shard import AuthorityShard

        absolute_path = self.project_root / shard_path
        if create_if_missing and not absolute_path.exists():
            return AuthorityShard(path=shard_path, blocks=[])
        return AuthorityShard.load(self.project_root, shard_path)

    def _mark_shard_changed(self, shard_path: Path, shard) -> None:  # noqa: ANN001
        """Mark or immediately persist a changed shard.

        Args:
            shard_path: Project-relative shard path.
            shard: Authority shard instance that has changed.
        """
        if self._shard_unit_of_work is not None:
            self._shard_unit_of_work.mark_changed(shard_path)
            return
        shard.sort_blocks()
        shard.save(self.project_root)

    def _apply_move_block(
        self,
        operation: MoveBlockOperation,
        result: AuthorityPatchResult,
        label: str,
    ) -> None:
        """Move a block from source shard to target shard.

        Args:
            operation: Move operation details.
            result: Result object to record outcomes.
            label: Operation label.
        """
        source_shard = self._load_shard_for_patch(operation.source_shard_path)
        block_data = source_shard.remove_block(operation.block_id)
        if block_data is None:
            result.add_skipped(label, f"block '{operation.block_id}' not found in source")
            return

        self._mark_shard_changed(operation.source_shard_path, source_shard)
        result.add_modified(operation.source_shard_path)

        target_shard = self._load_shard_for_patch(
            operation.target_shard_path,
            create_if_missing=operation.create_target_if_missing,
        )
        target_shard.add_block(block_data)
        self._mark_shard_changed(operation.target_shard_path, target_shard)
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
            operation: Create operation details.
            result: Result object to record outcomes.
            label: Operation label.
        """
        target_shard = self._load_shard_for_patch(
            operation.target_shard_path,
            create_if_missing=operation.create_target_if_missing,
        )
        target_shard.add_block(operation.block_data)
        self._mark_shard_changed(operation.target_shard_path, target_shard)
        result.add_modified(operation.target_shard_path)
        result.add_applied(label)

    def _apply_delete_block(
        self,
        operation: DeleteBlockOperation,
        result: AuthorityPatchResult,
        label: str,
    ) -> None:
        """Delete a block from a shard.

        Args:
            operation: Delete operation details.
            result: Result object to record outcomes.
            label: Operation label.
        """
        source_shard = self._load_shard_for_patch(operation.source_shard_path)
        source_shard.remove_block(operation.block_id)
        self._mark_shard_changed(operation.source_shard_path, source_shard)
        result.add_modified(operation.source_shard_path)
        result.add_applied(label)

    def _apply_update_metadata(
        self,
        operation: UpdateBlockMetadataOperation,
        result: AuthorityPatchResult,
        label: str,
    ) -> None:
        """Update main metadata fields on a block."""
        block = self._get_mutable_block(operation.source_shard_path, operation.block_id)
        if block is None:
            result.add_skipped(label, f"block '{operation.block_id}' not found")
            return
        for field_name, field_value in operation.metadata_changes.items():
            block[field_name] = field_value
        self._save_mutated_block(operation.source_shard_path, operation.block_id, block)
        result.add_modified(operation.source_shard_path)
        result.add_applied(label)

    def _apply_update_location(
        self,
        operation: UpdateBlockLocationOperation,
        result: AuthorityPatchResult,
        label: str,
    ) -> None:
        """Update a block code path.

        Args:
            operation: Location update details.
            result: Result object to record outcomes.
            label: Operation label.
        """
        block = self._get_mutable_block(operation.source_shard_path, operation.block_id)
        if block is None:
            result.add_skipped(label, f"block '{operation.block_id}' not found")
            return
        code = block.setdefault("code", {})
        if not isinstance(code, dict):
            code = {}
            block["code"] = code
        code["path"] = operation.new_path
        self._save_mutated_block(operation.source_shard_path, operation.block_id, block)
        result.add_modified(operation.source_shard_path)
        result.add_applied(label)

    def _apply_update_symbol(
        self,
        operation: UpdateBlockSymbolOperation,
        result: AuthorityPatchResult,
        label: str,
    ) -> None:
        """Update a block code symbol and optional display name.

        Args:
            operation: Symbol update details.
            result: Result object to record outcomes.
            label: Operation label.
        """
        block = self._get_mutable_block(operation.source_shard_path, operation.block_id)
        if block is None:
            result.add_skipped(label, f"block '{operation.block_id}' not found")
            return
        code = block.setdefault("code", {})
        if not isinstance(code, dict):
            code = {}
            block["code"] = code
        code["symbol"] = operation.new_symbol
        if operation.new_name is not None:
            block["name"] = operation.new_name
        self._save_mutated_block(operation.source_shard_path, operation.block_id, block)
        result.add_modified(operation.source_shard_path)
        result.add_applied(label)

    def _apply_update_code_reference(
        self,
        operation: UpdateBlockCodeReferenceOperation,
        result: AuthorityPatchResult,
        label: str,
    ) -> None:
        """Update a block code path, symbol, optional kind, and optional name.

        Args:
            operation: Code reference update details.
            result: Result object to record outcomes.
            label: Operation label.
        """
        block = self._get_mutable_block(operation.source_shard_path, operation.block_id)
        if block is None:
            result.add_skipped(label, f"block '{operation.block_id}' not found")
            return
        code = block.setdefault("code", {})
        if not isinstance(code, dict):
            code = {}
            block["code"] = code
        code["path"] = operation.new_path
        code["symbol"] = operation.new_symbol
        if operation.new_kind is not None:
            code["kind"] = operation.new_kind
        if operation.new_name is not None:
            block["name"] = operation.new_name
        self._save_mutated_block(operation.source_shard_path, operation.block_id, block)
        result.add_modified(operation.source_shard_path)
        result.add_applied(label)

    def _apply_add_ignore_rule(
        self,
        operation: AddIgnoreRuleOperation,
        result: AuthorityPatchResult,
        label: str,
    ) -> None:
        """Add an ignored-code rule to the root blueprint.

        Args:
            operation: Ignore-rule creation details.
            result: Result object to record outcomes.
            label: Operation label.
        """
        data = self._load_blueprint_index(operation.blueprint_path)
        authority = data.setdefault("authority", {})
        if not isinstance(authority, dict):
            authority = {}
            data["authority"] = authority
        ignored_code = authority.setdefault("ignored_code", [])
        if not isinstance(ignored_code, list):
            ignored_code = []
            authority["ignored_code"] = ignored_code
        if operation.rule_data not in ignored_code:
            ignored_code.append(dict(operation.rule_data))
        self._save_blueprint_index(operation.blueprint_path, data)
        result.add_modified(operation.blueprint_path)
        result.add_applied(label)

    def _apply_remove_ignore_rule(
        self,
        operation: RemoveIgnoreRuleOperation,
        result: AuthorityPatchResult,
        label: str,
    ) -> None:
        """Remove an ignored-code rule from the root blueprint.

        Args:
            operation: Ignore-rule removal details.
            result: Result object to record outcomes.
            label: Operation label.
        """
        data = self._load_blueprint_index(operation.blueprint_path)
        authority = data.get("authority")
        if not isinstance(authority, dict):
            result.add_skipped(label, "authority section not found")
            return
        ignored_code = authority.get("ignored_code")
        if not isinstance(ignored_code, list):
            result.add_skipped(label, "ignored_code section not found")
            return
        remaining = [rule for rule in ignored_code if rule != operation.rule_data]
        authority["ignored_code"] = remaining
        self._save_blueprint_index(operation.blueprint_path, data)
        result.add_modified(operation.blueprint_path)
        result.add_applied(label)


    def _apply_add_covered_code(
        self,
        operation: AddCoveredCodeOperation,
        result: AuthorityPatchResult,
        label: str,
    ) -> None:
        """Add a covered-code relation to the root blueprint.

        Args:
            operation: Covered-code creation details.
            result: Result object to record outcomes.
            label: Operation label.
        """
        data = self._load_blueprint_index(operation.blueprint_path)
        authority = data.setdefault("authority", {})
        if not isinstance(authority, dict):
            authority = {}
            data["authority"] = authority
        covered_code = authority.setdefault("covered_code", [])
        if not isinstance(covered_code, list):
            covered_code = []
            authority["covered_code"] = covered_code
        if operation.rule_data not in covered_code:
            covered_code.append(dict(operation.rule_data))
        self._save_blueprint_index(operation.blueprint_path, data)
        result.add_modified(operation.blueprint_path)
        result.add_applied(label)

    def _apply_remove_covered_code(
        self,
        operation: RemoveCoveredCodeOperation,
        result: AuthorityPatchResult,
        label: str,
    ) -> None:
        """Remove a covered-code relation from the root blueprint.

        Args:
            operation: Covered-code removal details.
            result: Result object to record outcomes.
            label: Operation label.
        """
        data = self._load_blueprint_index(operation.blueprint_path)
        authority = data.get("authority")
        if not isinstance(authority, dict):
            result.add_skipped(label, "authority section not found")
            return
        covered_code = authority.get("covered_code")
        if not isinstance(covered_code, list):
            result.add_skipped(label, "covered_code section not found")
            return
        remaining = [rule for rule in covered_code if rule != operation.rule_data]
        authority["covered_code"] = remaining
        self._save_blueprint_index(operation.blueprint_path, data)
        result.add_modified(operation.blueprint_path)
        result.add_applied(label)

    def _apply_create_shard_file(
        self,
        operation: CreateShardFileOperation,
        result: AuthorityPatchResult,
        label: str,
    ) -> None:
        """Create a new shard file.

        Args:
            operation: Shard creation details.
            result: Result object to record outcomes.
            label: Operation label.
        """
        target_absolute = self.project_root / operation.shard_path
        target_absolute.parent.mkdir(parents=True, exist_ok=True)
        target_absolute.write_text(
            yaml.safe_dump({"blocks": operation.initial_blocks}, sort_keys=False),
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
            operation: Shard deletion details.
            result: Result object to record outcomes.
            label: Operation label.
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
            operation: Rename details.
            result: Result object to record outcomes.
            label: Operation label.
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
            operation: Move details.
            result: Result object to record outcomes.
            label: Operation label.
        """
        source_absolute = self.project_root / operation.source_shard_path
        target_absolute = self.project_root / operation.target_shard_path
        target_absolute.parent.mkdir(parents=True, exist_ok=True)
        source_absolute.rename(target_absolute)
        result.add_modified(operation.source_shard_path)
        result.add_modified(operation.target_shard_path)
        result.add_applied(label)

    def _get_mutable_block(self, shard_path: Path, block_id: str) -> dict | None:
        """Return a mutable copy of one block from a shard.

        Args:
            shard_path: Project-relative shard path.
            block_id: Block identifier.

        Returns:
            Block dictionary copy, or None when not found.
        """
        shard = self._load_shard_for_patch(shard_path)
        for block in shard.get_blocks():
            if isinstance(block, dict) and block.get("id") == block_id:
                return dict(block)
        return None

    def _save_mutated_block(self, shard_path: Path, block_id: str, block_data: dict) -> None:
        """Replace one block in a shard and save it.

        Args:
            shard_path: Project-relative shard path.
            block_id: Block identifier to replace.
            block_data: New block data.
        """
        shard = self._load_shard_for_patch(shard_path)
        blocks = shard.get_blocks()
        for index, block in enumerate(blocks):
            if isinstance(block, dict) and block.get("id") == block_id:
                blocks[index] = block_data
                break
        shard.set_blocks(blocks)
        self._mark_shard_changed(shard_path, shard)

    def _load_blueprint_index(self, blueprint_path: Path) -> dict:
        """Load the root blueprint YAML as a dictionary.

        Args:
            blueprint_path: Project-relative blueprint path.

        Returns:
            Loaded blueprint dictionary.

        Raises:
            ValueError: If the loaded YAML is not a dictionary.
        """
        absolute_path = self.project_root / blueprint_path
        data = yaml.safe_load(absolute_path.read_text(encoding="utf-8"))
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError(f"Root blueprint must be a mapping: {blueprint_path}")
        return data

    def _save_blueprint_index(self, blueprint_path: Path, data: dict) -> None:
        """Write the root blueprint YAML.

        Args:
            blueprint_path: Project-relative blueprint path.
            data: Blueprint dictionary to write.
        """
        absolute_path = self.project_root / blueprint_path
        absolute_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def _validate_yaml_files(self, paths: set[Path]) -> list[str]:
        """Validate that all written YAML files parse correctly.

        Args:
            paths: Project-relative paths to validate.

        Returns:
            List of validation messages.
        """
        errors: list[str] = []
        for relative_path in paths:
            if relative_path.suffix not in {".yaml", ".yml"}:
                continue
            absolute_path = self.project_root / relative_path
            if not absolute_path.exists():
                continue
            try:
                yaml.safe_load(absolute_path.read_text(encoding="utf-8"))
            except yaml.YAMLError as yaml_error:
                errors.append(f"Invalid YAML in {relative_path}: {yaml_error}")
        return errors

    def _include_created_shard(self, operation: PatchOperation, include_set: set[str]) -> bool:
        """Add a newly created shard file to the manifest include set.

        Args:
            operation: Patch operation that created a shard file.
            include_set: Current manifest include set.

        Returns:
            True when the include set changed.
        """
        include_path = str(operation.shard_path)
        if include_path in include_set:
            return False
        include_set.add(include_path)
        return True

    def _include_target_shard(self, operation: PatchOperation, include_set: set[str]) -> bool:
        """Add an operation target shard to the manifest include set.

        Args:
            operation: Patch operation with a target shard path.
            include_set: Current manifest include set.

        Returns:
            True when the include set changed.
        """
        include_path = str(operation.target_shard_path)
        if include_path in include_set:
            return False
        include_set.add(include_path)
        return True

    def _remove_deleted_shard_include(self, operation: PatchOperation, include_set: set[str]) -> bool:
        """Remove a deleted shard file from the manifest include set.

        Args:
            operation: Patch operation that deleted a shard file.
            include_set: Current manifest include set.

        Returns:
            True when the include set changed.
        """
        include_path = str(operation.shard_path)
        if include_path not in include_set:
            return False
        include_set.discard(include_path)
        return True

    def _replace_moved_shard_include(self, operation: PatchOperation, include_set: set[str]) -> bool:
        """Replace an old shard include with its new location.

        Args:
            operation: Patch operation that moved or renamed a shard file.
            include_set: Current manifest include set.

        Returns:
            True when the include set changed.
        """
        old_include = str(operation.source_shard_path)
        new_include = str(operation.target_shard_path)
        if old_include not in include_set:
            return False
        include_set.discard(old_include)
        include_set.add(new_include)
        return True

    def _update_manifest_includes(
        self,
        plan: AuthorityPatchPlan,
        result: AuthorityPatchResult,
    ) -> None:
        """Update root blueprint includes after shard file lifecycle changes.

        Args:
            plan: Applied patch plan.
            result: Result object to record modifications.
        """
        manifest_path = Path("bpfw/blueprint.yaml")
        absolute_path = self.project_root / manifest_path
        if not absolute_path.exists():
            return

        data = yaml.safe_load(absolute_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return

        includes = data.get("includes", [])
        if not isinstance(includes, list):
            includes = []
        include_set = {include for include in includes if isinstance(include, str)}

        changed = False
        for operation in plan.sorted_operations():
            handler = self._manifest_include_handlers.get(operation.kind)
            if handler is not None and handler(operation, include_set):
                changed = True

        if changed:
            data["includes"] = sorted(include_set)
            absolute_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            result.manifest_updated = True
            result.add_modified(manifest_path)

