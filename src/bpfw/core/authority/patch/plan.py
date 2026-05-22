"""Mechanical authority patch plan for Blueprint Engine.

A plan stores explicit operations that will be applied by the low-level
``AuthorityPatchEngine``. The plan itself is read-only and never modifies files.
"""

from pathlib import Path
from typing import Union

from bpfw.core.authority.errors import AuthorityError
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

PatchOperation = Union[
    MoveBlockOperation,
    CreateBlockOperation,
    DeleteBlockOperation,
    UpdateBlockMetadataOperation,
    UpdateBlockLocationOperation,
    UpdateBlockSymbolOperation,
    UpdateBlockCodeReferenceOperation,
    AddIgnoreRuleOperation,
    RemoveIgnoreRuleOperation,
    AddCoveredCodeOperation,
    RemoveCoveredCodeOperation,
    CreateShardFileOperation,
    DeleteShardFileOperation,
    RenameShardFileOperation,
    MoveShardFileOperation,
]

_BLOCK_OPERATIONS: frozenset[PatchOperationKind] = frozenset(
    {
        PatchOperationKind.MOVE_BLOCK,
        PatchOperationKind.CREATE_BLOCK,
        PatchOperationKind.DELETE_BLOCK,
        PatchOperationKind.UPDATE_BLOCK_METADATA,
        PatchOperationKind.UPDATE_BLOCK_LOCATION,
        PatchOperationKind.UPDATE_BLOCK_SYMBOL,
        PatchOperationKind.UPDATE_BLOCK_CODE_REFERENCE,
    }
)

_BLUEPRINT_INDEX_OPERATIONS: frozenset[PatchOperationKind] = frozenset(
    {
        PatchOperationKind.ADD_IGNORE_RULE,
        PatchOperationKind.REMOVE_IGNORE_RULE,
        PatchOperationKind.ADD_COVERED_CODE,
        PatchOperationKind.REMOVE_COVERED_CODE,
    }
)

_SHARD_FILE_OPERATIONS: frozenset[PatchOperationKind] = frozenset(
    {
        PatchOperationKind.CREATE_SHARD_FILE,
        PatchOperationKind.DELETE_SHARD_FILE,
        PatchOperationKind.RENAME_SHARD_FILE,
        PatchOperationKind.MOVE_SHARD_FILE,
    }
)

_APPLICATION_ORDER: dict[PatchOperationKind, int] = {
    PatchOperationKind.CREATE_SHARD_FILE: 0,
    PatchOperationKind.MOVE_SHARD_FILE: 1,
    PatchOperationKind.RENAME_SHARD_FILE: 2,
    PatchOperationKind.MOVE_BLOCK: 3,
    PatchOperationKind.CREATE_BLOCK: 4,
    PatchOperationKind.UPDATE_BLOCK_METADATA: 5,
    PatchOperationKind.UPDATE_BLOCK_LOCATION: 6,
    PatchOperationKind.UPDATE_BLOCK_SYMBOL: 7,
    PatchOperationKind.UPDATE_BLOCK_CODE_REFERENCE: 8,
    PatchOperationKind.ADD_IGNORE_RULE: 9,
    PatchOperationKind.REMOVE_IGNORE_RULE: 10,
    PatchOperationKind.ADD_COVERED_CODE: 11,
    PatchOperationKind.REMOVE_COVERED_CODE: 12,
    PatchOperationKind.DELETE_BLOCK: 13,
    PatchOperationKind.DELETE_SHARD_FILE: 14,
}


class AuthorityPatchPlan:
    """Represent a list of explicit authority patch operations.

    The plan stores operations, reports affected files, and validates
    preconditions. It does not decide whether operations are semantically right.
    """

    def __init__(self) -> None:
        """Initialize an empty patch plan."""
        self._operations: list[PatchOperation] = []

    def add_operation(self, operation: PatchOperation) -> None:
        """Append one operation to the plan.

        Args:
            operation: Supported mechanical operation to append.
        """
        self._operations.append(operation)

    @property
    def operations(self) -> list[PatchOperation]:
        """Return operations in insertion order.

        Returns:
            Copy of the operation list.
        """
        return list(self._operations)

    def is_empty(self) -> bool:
        """Return whether the plan contains no operations.

        Returns:
            True when no operations are present.
        """
        return len(self._operations) == 0

    def operation_count(self) -> int:
        """Return the number of operations in the plan.

        Returns:
            Operation count.
        """
        return len(self._operations)

    def affected_files(self) -> set[Path]:
        """Return all project-relative paths touched by the plan.

        Returns:
            Set of affected paths.
        """
        collected: set[Path] = set()
        for operation in self._operations:
            collected.update(operation.affected_files())
        if self.requires_manifest_update() or self.writes_blueprint_index():
            collected.add(Path("bpfw/blueprint.yaml"))
        return collected

    def affected_authority_files(self) -> set[Path]:
        """Return YAML authority files affected by this plan.

        Returns:
            Set of YAML files under ``bpfw/``.
        """
        return {
            path
            for path in self.affected_files()
            if path.suffix in {".yaml", ".yml"} and path.parts and path.parts[0] == "bpfw"
        }

    def affected_shard_files(self) -> set[Path]:
        """Return shard files affected by this plan.

        Returns:
            Set of paths under ``bpfw/blocks/``.
        """
        return {
            path
            for path in self.affected_files()
            if len(path.parts) >= 2 and path.parts[0] == "bpfw" and path.parts[1] == "blocks"
        }

    def requires_manifest_update(self) -> bool:
        """Return whether applying the plan requires root include updates.

        Returns:
            True when shard creation, movement, deletion, or block placement
            operations may require the root include list to change.
        """
        for operation in self._operations:
            if operation.kind in _SHARD_FILE_OPERATIONS:
                return True
            if operation.kind in {PatchOperationKind.CREATE_BLOCK, PatchOperationKind.MOVE_BLOCK}:
                return True
        return False

    def writes_blueprint_index(self) -> bool:
        """Return whether the plan writes the root blueprint file directly.

        Returns:
            True when an index-level operation is present.
        """
        for operation in self._operations:
            if operation.kind in _BLUEPRINT_INDEX_OPERATIONS:
                return True
        return False

    def sorted_operations(self) -> list[PatchOperation]:
        """Return operations in deterministic application order.

        Returns:
            Sorted operation list.
        """
        return sorted(
            self._operations,
            key=lambda operation: _APPLICATION_ORDER.get(operation.kind, 99),
        )

    def validate(self, project_root: Path) -> list[str]:
        """Validate all operations and collect readable errors.

        Args:
            project_root: Project root directory.

        Returns:
            Empty list when valid, otherwise validation messages.
        """
        errors: list[str] = []
        for operation in self._operations:
            try:
                operation.validate(project_root)
            except AuthorityError as error:
                errors.append(f"[{operation.kind.value}] {error}")
        return errors
