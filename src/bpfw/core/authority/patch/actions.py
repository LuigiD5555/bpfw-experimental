"""Mechanical authority patch operations for Blueprint Engine.

Each operation describes one explicit mutation to files under ``bpfw/``.
Operations do not detect drift and do not decide whether a change is valid
product-wise. They only validate mechanical preconditions before the engine
applies an already approved change.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from bpfw.core.authority.errors import AuthorityError, InvalidShardPathError


class PatchOperationKind(Enum):
    """Stable labels identifying each mechanical patch operation type."""

    MOVE_BLOCK = "move_block"
    CREATE_BLOCK = "create_block"
    DELETE_BLOCK = "delete_block"
    UPDATE_BLOCK_METADATA = "update_block_metadata"
    UPDATE_BLOCK_LOCATION = "update_block_location"
    UPDATE_BLOCK_SYMBOL = "update_block_symbol"
    UPDATE_BLOCK_CODE_REFERENCE = "update_block_code_reference"
    ADD_IGNORE_RULE = "add_ignore_rule"
    REMOVE_IGNORE_RULE = "remove_ignore_rule"
    ADD_COVERED_CODE = "add_covered_code"
    REMOVE_COVERED_CODE = "remove_covered_code"
    CREATE_SHARD_FILE = "create_shard_file"
    DELETE_SHARD_FILE = "delete_shard_file"
    RENAME_SHARD_FILE = "rename_shard_file"
    MOVE_SHARD_FILE = "move_shard_file"


def _validate_bpfw_path(relative_path: Path) -> None:
    """Verify that a path is inside the BPFW authority directory.

    Args:
        relative_path: Project-relative path to validate.

    Raises:
        InvalidShardPathError: If the path escapes the ``bpfw/`` directory.
    """

    parts = relative_path.parts
    if not parts or parts[0] != "bpfw":
        raise InvalidShardPathError(
            f"Authority path must be inside bpfw/ directory: {relative_path}"
        )
    if ".." in parts:
        raise InvalidShardPathError(
            f"Authority path must not contain '..' components: {relative_path}"
        )


def _validate_shard_path(shard_path: Path) -> None:
    """Verify that a shard path is inside ``bpfw/blocks/``.

    Args:
        shard_path: Project-relative shard path to validate.

    Raises:
        InvalidShardPathError: If the path is outside ``bpfw/blocks/``.
    """

    _validate_bpfw_path(shard_path)
    parts = shard_path.parts
    if len(parts) < 3 or parts[1] != "blocks":
        raise InvalidShardPathError(
            f"Shard path must be inside bpfw/blocks/: {shard_path}"
        )
    if shard_path.suffix not in {".yaml", ".yml"}:
        raise InvalidShardPathError(
            f"Shard path must be a YAML file: {shard_path}"
        )


def _validate_blueprint_path(relative_path: Path) -> None:
    """Verify that a path points to the root blueprint file.

    Args:
        relative_path: Project-relative path to validate.

    Raises:
        InvalidShardPathError: If the path is not ``bpfw/blueprint.yaml``.
    """

    _validate_bpfw_path(relative_path)
    if relative_path != Path("bpfw/blueprint.yaml"):
        raise InvalidShardPathError(
            f"Blueprint operation must target bpfw/blueprint.yaml: {relative_path}"
        )


def _validate_block_exists(project_root: Path, shard_path: Path, block_id: str) -> None:
    """Validate that a block exists in a shard.

    Args:
        project_root: Project root directory.
        shard_path: Project-relative shard path.
        block_id: Block identifier to find.

    Raises:
        AuthorityError: If the shard or block does not exist.
    """

    from bpfw.core.authority.shard import AuthorityShard

    if not block_id.strip():
        raise AuthorityError("Operation requires a non-empty block_id.")

    source_absolute = project_root / shard_path
    if not source_absolute.exists():
        raise AuthorityError(f"Source shard does not exist: {shard_path}")

    source_shard = AuthorityShard.load(project_root, shard_path)
    if not source_shard.contains_block_id(block_id):
        raise AuthorityError(
            f"Block '{block_id}' not found in source shard {shard_path}."
        )


@dataclass(frozen=True)
class PatchOperation:
    """Base data container for a single authority patch operation.

    Attributes:
        kind: Discriminator identifying the operation type.
    """

    kind: PatchOperationKind

    def affected_files(self) -> set[Path]:
        """Return project-relative files this operation may modify.

        Returns:
            Set of affected project-relative paths.
        """
        return set()

    def validate(self, project_root: Path) -> None:
        """Validate preconditions without modifying files.

        Args:
            project_root: Project root directory.

        Raises:
            AuthorityError: When a precondition is violated.
        """
        return None


@dataclass(frozen=True)
class MoveBlockOperation:
    """Move a block from one shard file to another.

    Attributes:
        block_id: Identifier of the block to move.
        source_shard_path: Project-relative shard that currently contains the block.
        target_shard_path: Project-relative shard that should receive the block.
        create_target_if_missing: Whether to create the target shard if missing.
    """

    kind: PatchOperationKind = field(default=PatchOperationKind.MOVE_BLOCK, init=False)
    block_id: str = ""
    source_shard_path: Path = field(default_factory=lambda: Path("."))
    target_shard_path: Path = field(default_factory=lambda: Path("."))
    create_target_if_missing: bool = False

    def affected_files(self) -> set[Path]:
        """Return source and target shard paths."""
        return {self.source_shard_path, self.target_shard_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the block move is mechanically safe.

        Args:
            project_root: Project root directory.

        Raises:
            AuthorityError: If the source, target, or block state is invalid.
        """
        from bpfw.core.authority.shard import AuthorityShard

        _validate_shard_path(self.source_shard_path)
        _validate_shard_path(self.target_shard_path)
        _validate_block_exists(project_root, self.source_shard_path, self.block_id)

        target_absolute = project_root / self.target_shard_path
        if target_absolute.exists():
            target_shard = AuthorityShard.load(project_root, self.target_shard_path)
            if target_shard.contains_block_id(self.block_id):
                raise AuthorityError(
                    f"Target shard {self.target_shard_path} already contains "
                    f"block '{self.block_id}'."
                )
        elif not self.create_target_if_missing:
            raise AuthorityError(
                f"Target shard does not exist: {self.target_shard_path}. "
                "Set create_target_if_missing=True to create it."
            )


@dataclass(frozen=True)
class CreateBlockOperation:
    """Create a new authority block in a target shard.

    Attributes:
        block_data: Complete block dictionary including ``id``.
        target_shard_path: Project-relative shard where the block will be created.
        create_target_if_missing: Whether to create the target shard if missing.
    """

    kind: PatchOperationKind = field(default=PatchOperationKind.CREATE_BLOCK, init=False)
    block_data: dict[str, Any] = field(default_factory=dict)
    target_shard_path: Path = field(default_factory=lambda: Path("."))
    create_target_if_missing: bool = False

    def affected_files(self) -> set[Path]:
        """Return the target shard path."""
        return {self.target_shard_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the block can be created safely.

        Args:
            project_root: Project root directory.

        Raises:
            AuthorityError: If the block data or target shard is invalid.
        """
        from bpfw.core.authority.shard import AuthorityShard

        _validate_shard_path(self.target_shard_path)
        if not isinstance(self.block_data, dict) or "id" not in self.block_data:
            raise AuthorityError("CreateBlockOperation requires block_data with an 'id' field.")

        block_id = self.block_data["id"]
        if not isinstance(block_id, str) or not block_id.strip():
            raise AuthorityError("Block 'id' must be a non-empty string.")

        target_absolute = project_root / self.target_shard_path
        if target_absolute.exists():
            target_shard = AuthorityShard.load(project_root, self.target_shard_path)
            if target_shard.contains_block_id(block_id):
                raise AuthorityError(
                    f"Target shard {self.target_shard_path} already contains "
                    f"block '{block_id}'."
                )
        elif not self.create_target_if_missing:
            raise AuthorityError(
                f"Target shard does not exist: {self.target_shard_path}. "
                "Set create_target_if_missing=True to create it."
            )


@dataclass(frozen=True)
class DeleteBlockOperation:
    """Remove a block from an authority shard.

    Attributes:
        block_id: Identifier of the block to delete.
        source_shard_path: Project-relative shard containing the block.
    """

    kind: PatchOperationKind = field(default=PatchOperationKind.DELETE_BLOCK, init=False)
    block_id: str = ""
    source_shard_path: Path = field(default_factory=lambda: Path("."))

    def affected_files(self) -> set[Path]:
        """Return the source shard path."""
        return {self.source_shard_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the block can be deleted.

        Args:
            project_root: Project root directory.
        """
        _validate_shard_path(self.source_shard_path)
        _validate_block_exists(project_root, self.source_shard_path, self.block_id)


@dataclass(frozen=True)
class UpdateBlockMetadataOperation:
    """Edit metadata fields for an existing authority block.

    Attributes:
        block_id: Identifier of the block to update.
        source_shard_path: Project-relative shard containing the block.
        metadata_changes: Top-level block metadata changes to apply.
    """

    kind: PatchOperationKind = field(default=PatchOperationKind.UPDATE_BLOCK_METADATA, init=False)
    block_id: str = ""
    source_shard_path: Path = field(default_factory=lambda: Path("."))
    metadata_changes: dict[str, Any] = field(default_factory=dict)

    ALLOWED_FIELDS: frozenset[str] = frozenset(
        {
            "name",
            "purpose",
            "domain",
            "lifecycle",
            "status",
            "observations",
            "notes",
            "replacement",
            "uniqueness",
            "duplicate_policy",
            "suspected_duplicates",
            "detected",
            "interface",
            "entrypoints",
            "connections",
        }
    )

    def affected_files(self) -> set[Path]:
        """Return the source shard path."""
        return {self.source_shard_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the metadata update can be applied.

        Args:
            project_root: Project root directory.

        Raises:
            AuthorityError: If fields, lifecycle, or block state are invalid.
        """
        _validate_shard_path(self.source_shard_path)
        _validate_block_exists(project_root, self.source_shard_path, self.block_id)

        if not self.metadata_changes:
            raise AuthorityError("UpdateBlockMetadataOperation requires at least one metadata change.")

        invalid_fields = set(self.metadata_changes.keys()) - self.ALLOWED_FIELDS
        if invalid_fields:
            raise AuthorityError(
                f"Metadata fields not allowed: {sorted(invalid_fields)}. "
                f"Allowed fields: {sorted(self.ALLOWED_FIELDS)}."
            )

        lifecycle_value = self.metadata_changes.get("lifecycle")
        if lifecycle_value is not None:
            valid_lifecycles = {"active", "experimental", "deprecated", "planned", "legacy", "disabled"}
            if lifecycle_value not in valid_lifecycles:
                raise AuthorityError(
                    f"Invalid lifecycle value '{lifecycle_value}'. "
                    f"Valid values: {sorted(valid_lifecycles)}."
                )


@dataclass(frozen=True)
class UpdateBlockLocationOperation:
    """Update the code path of an existing authority block.

    Attributes:
        block_id: Identifier of the block to update.
        source_shard_path: Project-relative shard containing the block.
        new_path: New project-relative source code path.
    """

    kind: PatchOperationKind = field(default=PatchOperationKind.UPDATE_BLOCK_LOCATION, init=False)
    block_id: str = ""
    source_shard_path: Path = field(default_factory=lambda: Path("."))
    new_path: str = ""

    def affected_files(self) -> set[Path]:
        """Return the source shard path."""
        return {self.source_shard_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the location update can be applied.

        Args:
            project_root: Project root directory.
        """
        _validate_shard_path(self.source_shard_path)
        _validate_block_exists(project_root, self.source_shard_path, self.block_id)
        if not isinstance(self.new_path, str) or not self.new_path.strip():
            raise AuthorityError("UpdateBlockLocationOperation requires a non-empty new_path.")


@dataclass(frozen=True)
class UpdateBlockSymbolOperation:
    """Update the code symbol of an existing authority block.

    Attributes:
        block_id: Identifier of the block to update.
        source_shard_path: Project-relative shard containing the block.
        new_symbol: New symbol name.
        new_name: Optional authority display name update.
    """

    kind: PatchOperationKind = field(default=PatchOperationKind.UPDATE_BLOCK_SYMBOL, init=False)
    block_id: str = ""
    source_shard_path: Path = field(default_factory=lambda: Path("."))
    new_symbol: str = ""
    new_name: str | None = None

    def affected_files(self) -> set[Path]:
        """Return the source shard path."""
        return {self.source_shard_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the symbol update can be applied.

        Args:
            project_root: Project root directory.
        """
        _validate_shard_path(self.source_shard_path)
        _validate_block_exists(project_root, self.source_shard_path, self.block_id)
        if not isinstance(self.new_symbol, str) or not self.new_symbol.strip():
            raise AuthorityError("UpdateBlockSymbolOperation requires a non-empty new_symbol.")


@dataclass(frozen=True)
class UpdateBlockCodeReferenceOperation:
    """Update path, symbol, and optional kind/name for an existing block.

    Attributes:
        block_id: Identifier of the block to update.
        source_shard_path: Project-relative shard containing the block.
        new_path: New source path.
        new_symbol: New source symbol.
        new_kind: Optional source symbol kind.
        new_name: Optional authority display name.
    """

    kind: PatchOperationKind = field(default=PatchOperationKind.UPDATE_BLOCK_CODE_REFERENCE, init=False)
    block_id: str = ""
    source_shard_path: Path = field(default_factory=lambda: Path("."))
    new_path: str = ""
    new_symbol: str = ""
    new_kind: str | None = None
    new_name: str | None = None

    def affected_files(self) -> set[Path]:
        """Return the source shard path."""
        return {self.source_shard_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the code reference update can be applied.

        Args:
            project_root: Project root directory.
        """
        _validate_shard_path(self.source_shard_path)
        _validate_block_exists(project_root, self.source_shard_path, self.block_id)
        if not isinstance(self.new_path, str) or not self.new_path.strip():
            raise AuthorityError("UpdateBlockCodeReferenceOperation requires a non-empty new_path.")
        if not isinstance(self.new_symbol, str) or not self.new_symbol.strip():
            raise AuthorityError("UpdateBlockCodeReferenceOperation requires a non-empty new_symbol.")
        if self.new_kind is not None and not self.new_kind.strip():
            raise AuthorityError("new_kind must be non-empty when provided.")


@dataclass(frozen=True)
class AddIgnoreRuleOperation:
    """Add a deliberate ignored-code rule to the root blueprint.

    Attributes:
        rule_data: Dictionary describing the ignored path/symbol and reason.
        blueprint_path: Root blueprint path, normally ``bpfw/blueprint.yaml``.
    """

    kind: PatchOperationKind = field(default=PatchOperationKind.ADD_IGNORE_RULE, init=False)
    rule_data: dict[str, Any] = field(default_factory=dict)
    blueprint_path: Path = field(default_factory=lambda: Path("bpfw/blueprint.yaml"))

    def affected_files(self) -> set[Path]:
        """Return the root blueprint path."""
        return {self.blueprint_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the ignore rule can be added.

        Args:
            project_root: Project root directory.
        """
        _validate_blueprint_path(self.blueprint_path)
        if not (project_root / self.blueprint_path).exists():
            raise AuthorityError(f"Blueprint file does not exist: {self.blueprint_path}")
        if not isinstance(self.rule_data, dict) or not self.rule_data:
            raise AuthorityError("AddIgnoreRuleOperation requires non-empty rule_data.")
        path_value = self.rule_data.get("path")
        symbol_value = self.rule_data.get("symbol")
        if not path_value and not symbol_value:
            raise AuthorityError("Ignore rule requires at least 'path' or 'symbol'.")


@dataclass(frozen=True)
class RemoveIgnoreRuleOperation:
    """Remove a deliberate ignored-code rule from the root blueprint.

    Attributes:
        rule_data: Dictionary used to find the ignored-code rule.
        blueprint_path: Root blueprint path, normally ``bpfw/blueprint.yaml``.
    """

    kind: PatchOperationKind = field(default=PatchOperationKind.REMOVE_IGNORE_RULE, init=False)
    rule_data: dict[str, Any] = field(default_factory=dict)
    blueprint_path: Path = field(default_factory=lambda: Path("bpfw/blueprint.yaml"))

    def affected_files(self) -> set[Path]:
        """Return the root blueprint path."""
        return {self.blueprint_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the ignore rule can be removed.

        Args:
            project_root: Project root directory.
        """
        _validate_blueprint_path(self.blueprint_path)
        if not (project_root / self.blueprint_path).exists():
            raise AuthorityError(f"Blueprint file does not exist: {self.blueprint_path}")
        if not isinstance(self.rule_data, dict) or not self.rule_data:
            raise AuthorityError("RemoveIgnoreRuleOperation requires non-empty rule_data.")


@dataclass(frozen=True)
class AddCoveredCodeOperation:
    """Add a covered-code relation to the root blueprint.

    Covered code is real code that is intentionally governed by an existing
    authority block instead of being declared as a separate block.

    Attributes:
        rule_data: Dictionary describing the covered path, symbol, owner block, and reason.
        blueprint_path: Root blueprint path, normally ``bpfw/blueprint.yaml``.
    """

    kind: PatchOperationKind = field(default=PatchOperationKind.ADD_COVERED_CODE, init=False)
    rule_data: dict[str, Any] = field(default_factory=dict)
    blueprint_path: Path = field(default_factory=lambda: Path("bpfw/blueprint.yaml"))

    def affected_files(self) -> set[Path]:
        """Return the root blueprint path.

        Returns:
            Set containing the project-relative root blueprint path.
        """
        return {self.blueprint_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the covered-code rule can be added.

        Args:
            project_root: Project root directory.

        Raises:
            AuthorityError: If the rule is incomplete or the blueprint is missing.
        """
        _validate_blueprint_path(self.blueprint_path)
        if not (project_root / self.blueprint_path).exists():
            raise AuthorityError(f"Blueprint file does not exist: {self.blueprint_path}")
        if not isinstance(self.rule_data, dict) or not self.rule_data:
            raise AuthorityError("AddCoveredCodeOperation requires non-empty rule_data.")
        path_value = self.rule_data.get("path")
        symbol_value = self.rule_data.get("symbol")
        owner_value = self.rule_data.get("covered_by")
        if not path_value or not symbol_value or not owner_value:
            raise AuthorityError("Covered-code rule requires 'path', 'symbol', and 'covered_by'.")


@dataclass(frozen=True)
class RemoveCoveredCodeOperation:
    """Remove a covered-code relation from the root blueprint.

    Attributes:
        rule_data: Dictionary used to find the covered-code rule.
        blueprint_path: Root blueprint path, normally ``bpfw/blueprint.yaml``.
    """

    kind: PatchOperationKind = field(default=PatchOperationKind.REMOVE_COVERED_CODE, init=False)
    rule_data: dict[str, Any] = field(default_factory=dict)
    blueprint_path: Path = field(default_factory=lambda: Path("bpfw/blueprint.yaml"))

    def affected_files(self) -> set[Path]:
        """Return the root blueprint path.

        Returns:
            Set containing the project-relative root blueprint path.
        """
        return {self.blueprint_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the covered-code rule can be removed.

        Args:
            project_root: Project root directory.

        Raises:
            AuthorityError: If the rule is incomplete or the blueprint is missing.
        """
        _validate_blueprint_path(self.blueprint_path)
        if not (project_root / self.blueprint_path).exists():
            raise AuthorityError(f"Blueprint file does not exist: {self.blueprint_path}")
        if not isinstance(self.rule_data, dict) or not self.rule_data:
            raise AuthorityError("RemoveCoveredCodeOperation requires non-empty rule_data.")


@dataclass(frozen=True)
class CreateShardFileOperation:
    """Create a new YAML shard file.

    Attributes:
        shard_path: Project-relative path for the new shard file.
        initial_blocks: Optional blocks to write immediately.
    """

    kind: PatchOperationKind = field(default=PatchOperationKind.CREATE_SHARD_FILE, init=False)
    shard_path: Path = field(default_factory=lambda: Path("."))
    initial_blocks: list[dict[str, Any]] = field(default_factory=list)

    def affected_files(self) -> set[Path]:
        """Return the shard path."""
        return {self.shard_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the shard file can be created.

        Args:
            project_root: Project root directory.
        """
        _validate_shard_path(self.shard_path)
        target_absolute = project_root / self.shard_path
        if target_absolute.exists():
            raise AuthorityError(f"Cannot create shard file: already exists at {self.shard_path}.")


@dataclass(frozen=True)
class DeleteShardFileOperation:
    """Delete a YAML shard file.

    Attributes:
        shard_path: Project-relative shard file to delete.
        require_empty: Whether deletion is refused when the shard contains blocks.
    """

    kind: PatchOperationKind = field(default=PatchOperationKind.DELETE_SHARD_FILE, init=False)
    shard_path: Path = field(default_factory=lambda: Path("."))
    require_empty: bool = True

    def affected_files(self) -> set[Path]:
        """Return the shard path."""
        return {self.shard_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the shard file can be deleted.

        Args:
            project_root: Project root directory.
        """
        from bpfw.core.authority.shard import AuthorityShard

        _validate_shard_path(self.shard_path)
        target_absolute = project_root / self.shard_path
        if not target_absolute.exists():
            raise AuthorityError(f"Cannot delete shard file: does not exist at {self.shard_path}.")
        if self.require_empty:
            shard = AuthorityShard.load(project_root, self.shard_path)
            if not shard.is_empty():
                raise AuthorityError(
                    f"Cannot delete non-empty shard {self.shard_path}. "
                    "Set require_empty=False to allow deleting non-empty shards."
                )


@dataclass(frozen=True)
class RenameShardFileOperation:
    """Rename a YAML shard file.

    Attributes:
        source_shard_path: Current project-relative shard path.
        target_shard_path: Desired project-relative shard path after renaming.
    """

    kind: PatchOperationKind = field(default=PatchOperationKind.RENAME_SHARD_FILE, init=False)
    source_shard_path: Path = field(default_factory=lambda: Path("."))
    target_shard_path: Path = field(default_factory=lambda: Path("."))

    def affected_files(self) -> set[Path]:
        """Return source and target paths."""
        return {self.source_shard_path, self.target_shard_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the shard rename can be performed.

        Args:
            project_root: Project root directory.
        """
        _validate_shard_path(self.source_shard_path)
        _validate_shard_path(self.target_shard_path)
        source_absolute = project_root / self.source_shard_path
        if not source_absolute.exists():
            raise AuthorityError(f"Source shard does not exist: {self.source_shard_path}")
        target_absolute = project_root / self.target_shard_path
        if target_absolute.exists():
            raise AuthorityError(f"Cannot rename: target already exists at {self.target_shard_path}.")


@dataclass(frozen=True)
class MoveShardFileOperation:
    """Move a YAML shard file to another shard location.

    Attributes:
        source_shard_path: Current project-relative shard path.
        target_shard_path: Desired project-relative shard path after moving.
    """

    kind: PatchOperationKind = field(default=PatchOperationKind.MOVE_SHARD_FILE, init=False)
    source_shard_path: Path = field(default_factory=lambda: Path("."))
    target_shard_path: Path = field(default_factory=lambda: Path("."))

    def affected_files(self) -> set[Path]:
        """Return source and target paths."""
        return {self.source_shard_path, self.target_shard_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the shard move can be performed.

        Args:
            project_root: Project root directory.
        """
        _validate_shard_path(self.source_shard_path)
        _validate_shard_path(self.target_shard_path)
        source_absolute = project_root / self.source_shard_path
        if not source_absolute.exists():
            raise AuthorityError(f"Source shard does not exist: {self.source_shard_path}")
        target_absolute = project_root / self.target_shard_path
        if target_absolute.exists():
            raise AuthorityError(f"Cannot move: target already exists at {self.target_shard_path}.")
