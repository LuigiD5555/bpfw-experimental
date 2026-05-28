"""PURPOSE file-change authority patch plan for Blueprint Engine
DOMAIN  blueprint file changes
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
    _validate_shard_path,
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
    """PURPOSE store information about a list of authority patch operations
    DOMAIN  blueprint file changes
    """

    def __init__(self) -> None:
        """PURPOSE set up an empty patch plan
        DOMAIN  blueprint file changes
        """
        self._operations: list[PatchOperation] = []

    def add_operation(self, operation: PatchOperation) -> None:
        """PURPOSE append one operation to the plan
        DOMAIN  blueprint file changes
        """
        self._operations.append(operation)

    @property
    def operations(self) -> list[PatchOperation]:
        """PURPOSE get operations in insertion order
        DOMAIN  blueprint file changes
        """
        return list(self._operations)

    def is_empty(self) -> bool:
        """PURPOSE check whether the plan contains no operations
        DOMAIN  blueprint file changes
        """
        return len(self._operations) == 0

    def operation_count(self) -> int:
        """PURPOSE get the number of operations in the plan
        DOMAIN  blueprint file changes
        """
        return len(self._operations)

    def affected_files(self) -> set[Path]:
        """PURPOSE get all project-relative paths touched by the plan
        DOMAIN  blueprint file changes
        """
        collected: set[Path] = set()
        for operation in self._operations:
            collected.update(operation.affected_files())
        if self.requires_manifest_update() or self.writes_blueprint_index():
            collected.add(Path("bpfw/blueprint.yaml"))
        return collected

    def affected_authority_files(self) -> set[Path]:
        """PURPOSE get YAML authority files affected by this plan
        DOMAIN  blueprint file changes
        """
        return {
            path
            for path in self.affected_files()
            if path.suffix in {".yaml", ".yml"} and path.parts and path.parts[0] == "bpfw"
        }

    def affected_shard_files(self) -> set[Path]:
        """PURPOSE get shard files affected by this plan
        DOMAIN  blueprint file changes
        """
        return {
            path
            for path in self.affected_files()
            if len(path.parts) >= 2 and path.parts[0] == "bpfw" and path.parts[1] == "blocks"
        }

    def requires_manifest_update(self) -> bool:
        """PURPOSE check whether applying the plan requires root include updates
        DOMAIN  blueprint file changes
        """
        for operation in self._operations:
            if operation.kind in _SHARD_FILE_OPERATIONS:
                return True
            if operation.kind in {PatchOperationKind.CREATE_BLOCK, PatchOperationKind.MOVE_BLOCK}:
                return True
        return False

    def writes_blueprint_index(self) -> bool:
        """PURPOSE check whether the plan writes the root blueprint file directly
        DOMAIN  blueprint file changes
        """
        for operation in self._operations:
            if operation.kind in _BLUEPRINT_INDEX_OPERATIONS:
                return True
        return False

    def sorted_operations(self) -> list[PatchOperation]:
        """PURPOSE get operations in stable application order
        DOMAIN  blueprint file changes
        """
        return sorted(
            self._operations,
            key=lambda operation: _APPLICATION_ORDER.get(operation.kind, 99),
        )

    def validate(self, project_root: Path) -> list[str]:
        """PURPOSE check all operations and collect readable errors
        DOMAIN  blueprint file changes
        """
        errors: list[str] = []
        code_reference_updates: list[UpdateBlockCodeReferenceOperation] = []
        for operation in self._operations:
            if operation.kind == PatchOperationKind.UPDATE_BLOCK_CODE_REFERENCE:
                code_reference_updates.append(operation)  # type: ignore[arg-type]
                continue
            try:
                operation.validate(project_root)
            except AuthorityError as error:
                errors.append(f"[{operation.kind.value}] {error}")
        errors.extend(_validate_code_reference_updates(project_root, code_reference_updates))
        return errors


def _validate_code_reference_updates(
    project_root: Path,
    operations: list[UpdateBlockCodeReferenceOperation],
) -> list[str]:
    """PURPOSE check code-reference updates without loading the same shard repeatedly
    DOMAIN  blueprint file changes
    """
    if not operations:
        return []

    errors: list[str] = []
    operations_by_shard: dict[Path, list[UpdateBlockCodeReferenceOperation]] = {}
    for operation in operations:
        operation_errors = _validate_code_reference_update_payload(operation)
        if operation_errors:
            errors.extend(operation_errors)
            continue
        operations_by_shard.setdefault(operation.source_shard_path, []).append(operation)

    from bpfw.core.authority.shard import AuthorityShard

    for shard_path, shard_operations in operations_by_shard.items():
        source_absolute = project_root / shard_path
        if not source_absolute.exists():
            for operation in shard_operations:
                errors.append(
                    f"[{operation.kind.value}] Source shard does not exist: {shard_path}"
                )
            continue
        try:
            shard = AuthorityShard.load(project_root, shard_path)
        except AuthorityError as error:
            for operation in shard_operations:
                errors.append(f"[{operation.kind.value}] {error}")
            continue

        block_ids = {
            block.get("id")
            for block in shard.get_blocks()
            if isinstance(block, dict) and isinstance(block.get("id"), str)
        }
        for operation in shard_operations:
            if operation.block_id not in block_ids:
                errors.append(
                    f"[{operation.kind.value}] Block '{operation.block_id}' not found "
                    f"in source shard {shard_path}."
                )
    return errors


def _validate_code_reference_update_payload(
    operation: UpdateBlockCodeReferenceOperation,
) -> list[str]:
    """PURPOSE check one code-reference update data without reading a shard
        DOMAIN  blueprint file changes

    """
    errors: list[str] = []
    try:
        _validate_shard_path(operation.source_shard_path)
    except AuthorityError as error:
        errors.append(f"[{operation.kind.value}] {error}")
    if not isinstance(operation.block_id, str) or not operation.block_id.strip():
        errors.append(f"[{operation.kind.value}] Operation requires a non-empty block_id.")
    if not isinstance(operation.new_path, str) or not operation.new_path.strip():
        errors.append(
            f"[{operation.kind.value}] UpdateBlockCodeReferenceOperation requires a non-empty new_path."
        )
    if not isinstance(operation.new_symbol, str) or not operation.new_symbol.strip():
        errors.append(
            f"[{operation.kind.value}] UpdateBlockCodeReferenceOperation requires a non-empty new_symbol."
        )
    if operation.new_kind is not None and not operation.new_kind.strip():
        errors.append(f"[{operation.kind.value}] new_kind must be non-empty when provided.")
    return errors
