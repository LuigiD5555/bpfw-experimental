"""Patch operation definitions for the internal authority patch engine.

Each operation describes one explicit mutation to authority shard files.
Operations do not make decisions — they only carry data and validate
preconditions before the engine applies them.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from bpfw.authority.errors import AuthorityError, InvalidShardPathError


class PatchOperationKind(Enum):
    """Stable labels identifying each patch operation type."""

    MOVE_BLOCK = "move_block"
    CREATE_BLOCK = "create_block"
    DELETE_BLOCK = "delete_block"
    UPDATE_BLOCK_METADATA = "update_block_metadata"
    CREATE_SHARD_FILE = "create_shard_file"
    DELETE_SHARD_FILE = "delete_shard_file"
    RENAME_SHARD_FILE = "rename_shard_file"
    MOVE_SHARD_FILE = "move_shard_file"


def _validate_shard_path(shard_path: Path) -> None:
    """Verify that a shard path is inside the allowed authority directory.

    The allowed directory is ``bpfw/blocks/`` relative to the project root.
    Path traversal (``..``) components are rejected.

    Args:
        shard_path: Project-relative path to validate.

    Raises:
        InvalidShardPathError: If the path escapes the allowed directory.
    """

    parts = shard_path.parts
    if not parts or parts[0] != "bpfw":
        raise InvalidShardPathError(
            f"Shard path must be inside bpfw/ directory: {shard_path}"
        )
    if ".." in parts:
        raise InvalidShardPathError(
            f"Shard path must not contain '..' components: {shard_path}"
        )


@dataclass(frozen=True)
class PatchOperation:
    """Base data container for a single authority patch operation.

    Concrete operation types are represented by separate frozen dataclasses
    that carry kind-specific fields. All operation types expose the same
    interface through ``affected_files()``, ``validate()``, and ``kind``.

    Attributes:
        kind: Discriminator identifying the operation type.
    """

    kind: PatchOperationKind

    def affected_files(self) -> set[Path]:
        """Return project-relative paths this operation will modify.

        Returns:
            Set of paths that may be read or written during apply.
        """
        return set()

    def validate(self, project_root: Path) -> None:
        """Validate preconditions without modifying any files.

        Args:
            project_root: The project root directory for resolving paths.

        Raises:
            AuthorityError: When a precondition is violated.
        """
        return None


@dataclass(frozen=True)
class MoveBlockOperation:
    """Move a block from one YAML shard file to another.

    The engine removes the block from ``source_shard_path`` and appends it
    to ``target_shard_path``. Block data is preserved exactly.

    Attributes:
        block_id: Identifier of the block to move.
        source_shard_path: Project-relative path of the shard that currently
            contains the block.
        target_shard_path: Project-relative path of the destination shard.
        create_target_if_missing: When True, create the target shard file if
            it does not exist. When False, validation fails if the target is
            missing.
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
        """Validate that the move can be performed safely.

        Args:
            project_root: The project root directory.

        Raises:
            AuthorityError: If source shard does not exist.
            AuthorityError: If the block is not found in the source shard.
            AuthorityError: If the target shard already contains a block with
                the same id.
            InvalidShardPathError: If either path is outside the allowed
                directory.
        """
        from bpfw.authority.shard import AuthorityShard

        _validate_shard_path(self.source_shard_path)
        _validate_shard_path(self.target_shard_path)

        if not self.block_id:
            raise AuthorityError("MoveBlockOperation requires a non-empty block_id.")

        source_absolute = project_root / self.source_shard_path
        if not source_absolute.exists():
            raise AuthorityError(
                f"Source shard does not exist: {self.source_shard_path}"
            )

        source_shard = AuthorityShard.load(project_root, self.source_shard_path)
        if not source_shard.contains_block_id(self.block_id):
            raise AuthorityError(
                f"Block '{self.block_id}' not found in source shard "
                f"{self.source_shard_path}."
            )

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
                f"Set create_target_if_missing=True to create it."
            )


@dataclass(frozen=True)
class CreateBlockOperation:
    """Create a new authority block in a target shard.

    Attributes:
        block_data: Complete block dictionary including ``id`` and all
            required fields.
        target_shard_path: Project-relative path where the block will be
            created.
        create_target_if_missing: When True, create the target shard file if
            it does not exist.
    """

    kind: PatchOperationKind = field(
        default=PatchOperationKind.CREATE_BLOCK, init=False
    )
    block_data: dict[str, Any] = field(default_factory=dict)
    target_shard_path: Path = field(default_factory=lambda: Path("."))
    create_target_if_missing: bool = False

    def affected_files(self) -> set[Path]:
        """Return the target shard path."""
        return {self.target_shard_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the block can be created safely.

        Args:
            project_root: The project root directory.

        Raises:
            AuthorityError: If block_data is missing required fields.
            AuthorityError: If a block with the same id already exists in
                the target shard.
            InvalidShardPathError: If the target path is outside the allowed
                directory.
        """
        from bpfw.authority.shard import AuthorityShard

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
                f"Set create_target_if_missing=True to create it."
            )


@dataclass(frozen=True)
class DeleteBlockOperation:
    """Remove a block from an authority shard.

    The shard file itself is not deleted. Use ``DeleteShardFileOperation``
    separately if the empty shard should also be removed.

    Attributes:
        block_id: Identifier of the block to delete.
        source_shard_path: Project-relative path of the shard containing the
            block.
    """

    kind: PatchOperationKind = field(
        default=PatchOperationKind.DELETE_BLOCK, init=False
    )
    block_id: str = ""
    source_shard_path: Path = field(default_factory=lambda: Path("."))

    def affected_files(self) -> set[Path]:
        """Return the source shard path."""
        return {self.source_shard_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the block can be deleted.

        Args:
            project_root: The project root directory.

        Raises:
            AuthorityError: If the source shard does not exist.
            AuthorityError: If the block is not found in the source shard.
            InvalidShardPathError: If the path is outside the allowed
                directory.
        """
        from bpfw.authority.shard import AuthorityShard

        _validate_shard_path(self.source_shard_path)

        if not self.block_id:
            raise AuthorityError("DeleteBlockOperation requires a non-empty block_id.")

        source_absolute = project_root / self.source_shard_path
        if not source_absolute.exists():
            raise AuthorityError(
                f"Source shard does not exist: {self.source_shard_path}"
            )

        source_shard = AuthorityShard.load(project_root, self.source_shard_path)
        if not source_shard.contains_block_id(self.block_id):
            raise AuthorityError(
                f"Block '{self.block_id}' not found in source shard "
                f"{self.source_shard_path}."
            )


@dataclass(frozen=True)
class UpdateBlockMetadataOperation:
    """Edit metadata fields for an existing authority block.

    Only the fields listed in ``metadata_changes`` are overwritten.
    Unspecified fields remain untouched.

    Attributes:
        block_id: Identifier of the block to update.
        source_shard_path: Project-relative path of the shard containing the
            block.
        metadata_changes: Dictionary of field names and their new values.
            Allowed keys: ``name``, ``purpose``, ``domain``, ``lifecycle``,
            ``observations``, ``location``, and duplicate policy fields that
            the current schema supports.
    """

    kind: PatchOperationKind = field(
        default=PatchOperationKind.UPDATE_BLOCK_METADATA, init=False
    )
    block_id: str = ""
    source_shard_path: Path = field(default_factory=lambda: Path("."))
    metadata_changes: dict[str, Any] = field(default_factory=dict)

    ALLOWED_FIELDS: frozenset[str] = frozenset(
        {
            "name",
            "purpose",
            "domain",
            "lifecycle",
            "observations",
            "notes",
        }
    )

    def affected_files(self) -> set[Path]:
        """Return the source shard path."""
        return {self.source_shard_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the metadata update can be applied.

        Args:
            project_root: The project root directory.

        Raises:
            AuthorityError: If the block does not exist in the shard.
            AuthorityError: If any metadata field name is not allowed.
            AuthorityError: If ``lifecycle`` is provided with an invalid
                value.
            InvalidShardPathError: If the path is outside the allowed
                directory.
        """
        from bpfw.authority.shard import AuthorityShard

        _validate_shard_path(self.source_shard_path)

        if not self.block_id:
            raise AuthorityError(
                "UpdateBlockMetadataOperation requires a non-empty block_id."
            )
        if not self.metadata_changes:
            raise AuthorityError(
                "UpdateBlockMetadataOperation requires at least one metadata change."
            )

        invalid_fields = set(self.metadata_changes.keys()) - self.ALLOWED_FIELDS
        if invalid_fields:
            raise AuthorityError(
                f"Metadata fields not allowed: {sorted(invalid_fields)}. "
                f"Allowed fields: {sorted(self.ALLOWED_FIELDS)}."
            )

        lifecycle_value = self.metadata_changes.get("lifecycle")
        if lifecycle_value is not None:
            valid_lifecycles = {"active", "experimental", "deprecated", "planned"}
            if lifecycle_value not in valid_lifecycles:
                raise AuthorityError(
                    f"Invalid lifecycle value '{lifecycle_value}'. "
                    f"Valid values: {sorted(valid_lifecycles)}."
                )

        source_absolute = project_root / self.source_shard_path
        if not source_absolute.exists():
            raise AuthorityError(
                f"Source shard does not exist: {self.source_shard_path}"
            )

        source_shard = AuthorityShard.load(project_root, self.source_shard_path)
        if not source_shard.contains_block_id(self.block_id):
            raise AuthorityError(
                f"Block '{self.block_id}' not found in source shard "
                f"{self.source_shard_path}."
            )


@dataclass(frozen=True)
class CreateShardFileOperation:
    """Create a new YAML shard file.

    Attributes:
        shard_path: Project-relative path for the new shard file.
        initial_blocks: Optional list of block dictionaries to write into
            the new shard immediately.
    """

    kind: PatchOperationKind = field(
        default=PatchOperationKind.CREATE_SHARD_FILE, init=False
    )
    shard_path: Path = field(default_factory=lambda: Path("."))
    initial_blocks: list[dict[str, Any]] = field(default_factory=list)

    def affected_files(self) -> set[Path]:
        """Return the shard path."""
        return {self.shard_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the shard file can be created.

        Args:
            project_root: The project root directory.

        Raises:
            AuthorityError: If the file already exists.
            InvalidShardPathError: If the path is outside the allowed
                directory.
        """
        _validate_shard_path(self.shard_path)

        target_absolute = project_root / self.shard_path
        if target_absolute.exists():
            raise AuthorityError(
                f"Cannot create shard file: already exists at {self.shard_path}."
            )


@dataclass(frozen=True)
class DeleteShardFileOperation:
    """Delete a YAML shard file.

    For safety, ``require_empty`` defaults to ``True`` so that only empty
    shards are deleted unless the plan explicitly allows non-empty deletion.

    Attributes:
        shard_path: Project-relative path of the shard file to delete.
        require_empty: When True (default), refuse to delete a shard that
            still contains blocks.
    """

    kind: PatchOperationKind = field(
        default=PatchOperationKind.DELETE_SHARD_FILE, init=False
    )
    shard_path: Path = field(default_factory=lambda: Path("."))
    require_empty: bool = True

    def affected_files(self) -> set[Path]:
        """Return the shard path."""
        return {self.shard_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the shard file can be deleted.

        Args:
            project_root: The project root directory.

        Raises:
            AuthorityError: If the shard file does not exist.
            AuthorityError: If the shard is not empty and ``require_empty``
                is True.
            InvalidShardPathError: If the path is outside the allowed
                directory.
        """
        from bpfw.authority.shard import AuthorityShard

        _validate_shard_path(self.shard_path)

        target_absolute = project_root / self.shard_path
        if not target_absolute.exists():
            raise AuthorityError(
                f"Cannot delete shard file: does not exist at {self.shard_path}."
            )

        if self.require_empty:
            shard = AuthorityShard.load(project_root, self.shard_path)
            if not shard.is_empty():
                raise AuthorityError(
                    f"Cannot delete non-empty shard {self.shard_path}. "
                    f"Set require_empty=False to allow deleting non-empty shards."
                )


@dataclass(frozen=True)
class RenameShardFileOperation:
    """Rename a YAML shard file.

    Attributes:
        source_shard_path: Current project-relative path of the shard file.
        target_shard_path: Desired project-relative path after renaming.
    """

    kind: PatchOperationKind = field(
        default=PatchOperationKind.RENAME_SHARD_FILE, init=False
    )
    source_shard_path: Path = field(default_factory=lambda: Path("."))
    target_shard_path: Path = field(default_factory=lambda: Path("."))

    def affected_files(self) -> set[Path]:
        """Return source and target paths."""
        return {self.source_shard_path, self.target_shard_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the rename can be performed.

        Args:
            project_root: The project root directory.

        Raises:
            AuthorityError: If the source file does not exist.
            AuthorityError: If the target file already exists.
            InvalidShardPathError: If either path is outside the allowed
                directory.
        """
        _validate_shard_path(self.source_shard_path)
        _validate_shard_path(self.target_shard_path)

        source_absolute = project_root / self.source_shard_path
        if not source_absolute.exists():
            raise AuthorityError(
                f"Source shard does not exist: {self.source_shard_path}"
            )

        target_absolute = project_root / self.target_shard_path
        if target_absolute.exists():
            raise AuthorityError(
                f"Cannot rename: target already exists at {self.target_shard_path}."
            )


@dataclass(frozen=True)
class MoveShardFileOperation:
    """Move a YAML shard file to another authority shard location.

    Semantically identical to rename, but the target may be in a different
    subdirectory under ``bpfw/blocks/``.

    Attributes:
        source_shard_path: Current project-relative path of the shard file.
        target_shard_path: Desired project-relative path after moving.
    """

    kind: PatchOperationKind = field(
        default=PatchOperationKind.MOVE_SHARD_FILE, init=False
    )
    source_shard_path: Path = field(default_factory=lambda: Path("."))
    target_shard_path: Path = field(default_factory=lambda: Path("."))

    def affected_files(self) -> set[Path]:
        """Return source and target paths."""
        return {self.source_shard_path, self.target_shard_path}

    def validate(self, project_root: Path) -> None:
        """Validate that the move can be performed.

        Args:
            project_root: The project root directory.

        Raises:
            AuthorityError: If the source file does not exist.
            AuthorityError: If the target file already exists.
            InvalidShardPathError: If either path is outside the allowed
                directory.
        """
        _validate_shard_path(self.source_shard_path)
        _validate_shard_path(self.target_shard_path)

        source_absolute = project_root / self.source_shard_path
        if not source_absolute.exists():
            raise AuthorityError(
                f"Source shard does not exist: {self.source_shard_path}"
            )

        target_absolute = project_root / self.target_shard_path
        if target_absolute.exists():
            raise AuthorityError(
                f"Cannot move: target already exists at {self.target_shard_path}."
            )