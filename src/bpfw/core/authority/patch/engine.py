"""Low-level mechanical patch engine used by Blueprint Engine.

This engine applies explicit ``AuthorityPatchPlan`` instances safely with
validation, backups, rollback, and structured results. It is an internal writer
only. Read-only commands must never invoke it to silently synchronize drift.
"""

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

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
from bpfw.core.authority.patch.transaction import PatchWriteContext, TransactionBackup
from bpfw.core.catalog.access_control import (
    authorize_blueprint_writes_for_tool,
    authorize_temporary_blueprint_unlock_for_tool,
)
from bpfw.protection.authority import lock_authority, unlock_authority


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
    ) -> AuthorityPatchResult:
        """Apply a plan with explicit write permission.

        Args:
            plan: Mechanical patch plan to apply.
            write_context: Explicit permission context for guarded writes.

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
        backup = TransactionBackup(self.project_root)
        for relative_path in affected_files:
            backup.backup(relative_path)

        with self._write_authorization(write_context):
            try:
                self._apply_sorted_operations(plan, result)
            except (OSError, yaml.YAMLError, ValueError) as apply_error:
                result.error_message = f"Apply failed: {apply_error}"
                restored_paths = backup.rollback()
                result.rolled_back = True
                for restored_path in restored_paths:
                    result.messages.append(f"Rolled back: {restored_path}")
                return result

            yaml_errors = self._validate_yaml_files(affected_files)
            if yaml_errors:
                result.messages.append("YAML validation warning after apply:")
                for yaml_error in yaml_errors:
                    result.messages.append(f"  {yaml_error}")

            if plan.requires_manifest_update():
                self._update_manifest_includes(plan, result)

        backup.commit()
        result.success = True
        return result

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

    def collect_affected_files(self, plan: AuthorityPatchPlan) -> set[Path]:
        """Return all files the plan would modify.

        Args:
            plan: Plan to inspect.

        Returns:
            Set of affected project-relative paths.
        """
        return plan.affected_files()

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
    ) -> None:
        """Apply each operation in deterministic order.

        Args:
            plan: Plan whose sorted operations should be applied.
            result: Result object to record outcomes.
        """
        for operation in plan.sorted_operations():
            self._apply_single_operation(operation, result)

    def _apply_single_operation(
        self,
        operation: PatchOperation,
        result: AuthorityPatchResult,
    ) -> None:
        """Dispatch one operation to its handler.

        Args:
            operation: Operation to apply.
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
        elif kind == PatchOperationKind.UPDATE_BLOCK_LOCATION:
            self._apply_update_location(operation, result, label)  # type: ignore[arg-type]
        elif kind == PatchOperationKind.UPDATE_BLOCK_SYMBOL:
            self._apply_update_symbol(operation, result, label)  # type: ignore[arg-type]
        elif kind == PatchOperationKind.UPDATE_BLOCK_CODE_REFERENCE:
            self._apply_update_code_reference(operation, result, label)  # type: ignore[arg-type]
        elif kind == PatchOperationKind.ADD_IGNORE_RULE:
            self._apply_add_ignore_rule(operation, result, label)  # type: ignore[arg-type]
        elif kind == PatchOperationKind.REMOVE_IGNORE_RULE:
            self._apply_remove_ignore_rule(operation, result, label)  # type: ignore[arg-type]
        elif kind == PatchOperationKind.ADD_COVERED_CODE:
            self._apply_add_covered_code(operation, result, label)  # type: ignore[arg-type]
        elif kind == PatchOperationKind.REMOVE_COVERED_CODE:
            self._apply_remove_covered_code(operation, result, label)  # type: ignore[arg-type]
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
            operation: Move operation details.
            result: Result object to record outcomes.
            label: Operation label.
        """
        from bpfw.core.authority.shard import AuthorityShard

        source_shard = AuthorityShard.load(self.project_root, operation.source_shard_path)
        block_data = source_shard.remove_block(operation.block_id)
        if block_data is None:
            result.add_skipped(label, f"block '{operation.block_id}' not found in source")
            return

        source_shard.save(self.project_root)
        result.add_modified(operation.source_shard_path)

        target_absolute = self.project_root / operation.target_shard_path
        if not target_absolute.exists() and operation.create_target_if_missing:
            target_absolute.parent.mkdir(parents=True, exist_ok=True)
            target_absolute.write_text(yaml.safe_dump({"blocks": []}, sort_keys=False), encoding="utf-8")

        target_shard = AuthorityShard.load(self.project_root, operation.target_shard_path)
        target_shard.add_block(block_data)
        target_shard.sort_blocks()
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
            operation: Create operation details.
            result: Result object to record outcomes.
            label: Operation label.
        """
        from bpfw.core.authority.shard import AuthorityShard

        target_absolute = self.project_root / operation.target_shard_path
        if not target_absolute.exists() and operation.create_target_if_missing:
            target_absolute.parent.mkdir(parents=True, exist_ok=True)
            target_absolute.write_text(yaml.safe_dump({"blocks": []}, sort_keys=False), encoding="utf-8")

        target_shard = AuthorityShard.load(self.project_root, operation.target_shard_path)
        target_shard.add_block(operation.block_data)
        target_shard.sort_blocks()
        target_shard.save(self.project_root)
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
        from bpfw.core.authority.shard import AuthorityShard

        source_shard = AuthorityShard.load(self.project_root, operation.source_shard_path)
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
        """Update top-level metadata fields on a block.

        Args:
            operation: Metadata update details.
            result: Result object to record outcomes.
            label: Operation label.
        """
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
        from bpfw.core.authority.shard import AuthorityShard

        shard = AuthorityShard.load(self.project_root, shard_path)
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
        from bpfw.core.authority.shard import AuthorityShard

        shard = AuthorityShard.load(self.project_root, shard_path)
        blocks = shard.get_blocks()
        for index, block in enumerate(blocks):
            if isinstance(block, dict) and block.get("id") == block_id:
                blocks[index] = block_data
                break
        shard.set_blocks(blocks)
        shard.sort_blocks()
        shard.save(self.project_root)

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
            kind = operation.kind
            if kind == PatchOperationKind.CREATE_SHARD_FILE:
                include_path = str(operation.shard_path)  # type: ignore[union-attr]
                if include_path not in include_set:
                    include_set.add(include_path)
                    changed = True
            elif kind in {PatchOperationKind.CREATE_BLOCK, PatchOperationKind.MOVE_BLOCK}:
                include_path = str(operation.target_shard_path)  # type: ignore[union-attr]
                if include_path not in include_set:
                    include_set.add(include_path)
                    changed = True
            elif kind == PatchOperationKind.DELETE_SHARD_FILE:
                include_path = str(operation.shard_path)  # type: ignore[union-attr]
                if include_path in include_set:
                    include_set.discard(include_path)
                    changed = True
            elif kind in {PatchOperationKind.RENAME_SHARD_FILE, PatchOperationKind.MOVE_SHARD_FILE}:
                old_include = str(operation.source_shard_path)  # type: ignore[union-attr]
                new_include = str(operation.target_shard_path)  # type: ignore[union-attr]
                if old_include in include_set:
                    include_set.discard(old_include)
                    include_set.add(new_include)
                    changed = True

        if changed:
            data["includes"] = sorted(include_set)
            absolute_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            result.manifest_updated = True
            result.add_modified(manifest_path)
