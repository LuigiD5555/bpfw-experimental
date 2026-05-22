"""Authority patch plan model for the internal patch engine.

An ``AuthorityPatchPlan`` holds a list of explicit patch operations
that will be applied by ``AuthorityPatchEngine``. The plan itself
does not modify any files.
"""

from pathlib import Path
from typing import Union

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

# Union of all concrete operation types the plan accepts.
PatchOperation = Union[
    MoveBlockOperation,
    CreateBlockOperation,
    DeleteBlockOperation,
    UpdateBlockMetadataOperation,
    CreateShardFileOperation,
    DeleteShardFileOperation,
    RenameShardFileOperation,
    MoveShardFileOperation,
]

# Operations that modify blocks within shard files and therefore
# require a manifest update after application.
_BLOCK_OPERATIONS: frozenset[PatchOperationKind] = frozenset(
    {
        PatchOperationKind.MOVE_BLOCK,
        PatchOperationKind.CREATE_BLOCK,
        PatchOperationKind.DELETE_BLOCK,
        PatchOperationKind.UPDATE_BLOCK_METADATA,
    }
)

# Operations that create, delete, rename, or move shard files and
# therefore also require a manifest update.
_SHARD_FILE_OPERATIONS: frozenset[PatchOperationKind] = frozenset(
    {
        PatchOperationKind.CREATE_SHARD_FILE,
        PatchOperationKind.DELETE_SHARD_FILE,
        PatchOperationKind.RENAME_SHARD_FILE,
        PatchOperationKind.MOVE_SHARD_FILE,
    }
)

# Deterministic application order: shard file lifecycle first, then
# block-level mutations within shards.
_APPLICATION_ORDER: dict[PatchOperationKind, int] = {
    PatchOperationKind.CREATE_SHARD_FILE: 0,
    PatchOperationKind.MOVE_SHARD_FILE: 1,
    PatchOperationKind.RENAME_SHARD_FILE: 2,
    PatchOperationKind.MOVE_BLOCK: 3,
    PatchOperationKind.CREATE_BLOCK: 4,
    PatchOperationKind.UPDATE_BLOCK_METADATA: 5,
    PatchOperationKind.DELETE_BLOCK: 6,
    PatchOperationKind.DELETE_SHARD_FILE: 7,
}


class AuthorityPatchPlan:
    """Represent a list of explicit authority patch operations.

    The plan stores operations, reports affected files, and validates
    preconditions. It does **not** apply changes itself.

    Usage::

        plan = AuthorityPatchPlan()
        plan.add_operation(MoveBlockOperation(...))
        plan.validate(project_root)
        engine.apply(plan, write_context)
    """

    def __init__(self) -> None:
        self._operations: list[PatchOperation] = []

    def add_operation(self, operation: PatchOperation) -> None:
        """Append an operation to the plan.

        Args:
            operation: One of the supported patch operation types.
        """
        self._operations.append(operation)

    @property
    def operations(self) -> list[PatchOperation]:
        """Return the raw list of added operations.

        Returns:
            List of patch operations in insertion order.
        """
        return list(self._operations)

    def is_empty(self) -> bool:
        """Return whether the plan contains no operations.

        Returns:
            True when the plan has zero operations.
        """
        return len(self._operations) == 0

    def operation_count(self) -> int:
        """Return the number of operations in the plan.

        Returns:
            Integer count of operations.
        """
        return len(self._operations)

    def affected_files(self) -> set[Path]:
        """Return all project-relative paths touched by any operation.

        Returns:
            Set of paths that may be read or written during apply.
        """
        collected: set[Path] = set()
        for operation in self._operations:
            collected.update(operation.affected_files())
        return collected

    def affected_authority_files(self) -> set[Path]:
        """Return only shard YAML paths affected by this plan.

        Returns:
            Set of paths ending in ``.yaml`` inside ``bpfw/``.
        """
        return {
            path
            for path in self.affected_files()
            if path.suffix == ".yaml" and path.parts[0] == "bpfw"
        }

    def affected_shard_files(self) -> set[Path]:
        """Return only shard paths inside ``bpfw/blocks/``.

        Returns:
            Set of paths under ``bpfw/blocks/``.
        """
        return {
            path
            for path in self.affected_files()
            if len(path.parts) >= 2
            and path.parts[0] == "bpfw"
            and path.parts[1] == "blocks"
        }

    def requires_manifest_update(self) -> bool:
        """Return whether applying this plan requires a manifest update.

        Returns:
            True when any operation creates, deletes, renames, or moves
            shard files, or when blocks are moved between shards.
        """
        for operation in self._operations:
            if operation.kind in _BLOCK_OPERATIONS:
                return True
            if operation.kind in _SHARD_FILE_OPERATIONS:
                return True
        return False

    def sorted_operations(self) -> list[PatchOperation]:
        """Return operations in deterministic application order.

        Shard file lifecycle operations come first, followed by
        block-level mutations, followed by deletions.

        Returns:
            List of operations sorted by ``_APPLICATION_ORDER``.
        """
        return sorted(
            self._operations,
            key=lambda operation: _APPLICATION_ORDER.get(operation.kind, 99),
        )

    def validate(self, project_root: Path) -> list[str]:
        """Validate all operations and return collected error messages.

        Does not raise on the first error. Instead, collects all
        validation failures so the caller can report them together.

        Args:
            project_root: The project root directory for resolving paths.

        Returns:
            List of human-readable error strings. Empty when valid.
        """
        errors: list[str] = []
        for operation in self._operations:
            try:
                operation.validate(project_root)
            except Exception as error:
                errors.append(
                    f"[{operation.kind.value}] {error}"
                )
        return errors