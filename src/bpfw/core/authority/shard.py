"""Authority shard for BPFW block storage."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bpfw.core.authority.errors import InvalidAuthorityShardError
from bpfw.core.catalog.access_control import ensure_blueprint_can_be_written
from bpfw.core.yaml_io import dump_yaml_data, load_yaml_text


@dataclass(frozen=True)
class BlockOrigin:
    """Track which shard a block originated from."""

    block_id: str
    shard_path: Path  # Project-relative path


class AuthorityShard:
    """Represent a single shard file containing blocks.

    Shard files contain only:

    blocks:
      - ...

    They must not contain:
    - project
    - policy
    - authority
    - includes
    """

    def __init__(self, path: Path, blocks: list[dict[str, Any]]) -> None:
        """Initialize the authority shard.

        Args:
            path: Project-relative path to the shard file.
            blocks: List of block dictionaries.

        Raises:
            InvalidAuthorityShardError: If the shard is invalid.
        """
        self.path = path
        self._blocks = blocks
        self._validate()

    def _validate(self) -> None:
        """Validate the shard structure.

        Raises:
            InvalidAuthorityShardError: If validation fails.
        """
        if not isinstance(self._blocks, list):
            raise InvalidAuthorityShardError(
                f"Shard blocks must be a list, got {type(self._blocks).__name__}"
            )

        for block in self._blocks:
            if not isinstance(block, dict):
                raise InvalidAuthorityShardError(
                    f"Each block must be a dictionary, got {type(block).__name__}"
                )

            # Ensure each block has an ID
            if "id" not in block:
                raise InvalidAuthorityShardError(
                    f"Block missing 'id' field in shard {self.path}"
                )

    @classmethod
    def load(cls, project_root: Path, shard_path: Path) -> "AuthorityShard":
        """Load a shard file from the project root.

        Args:
            project_root: The project root directory.
            shard_path: Project-relative path to the shard file.

        Returns:
            Loaded AuthorityShard instance.

        Raises:
            InvalidAuthorityShardError: If the shard cannot be loaded or is invalid.
            FileNotFoundError: If the shard file does not exist.
        """
        # Resolve shard path relative to project root
        absolute_path = project_root / shard_path

        if not absolute_path.exists():
            raise FileNotFoundError(
                f"Shard file not found: {absolute_path}"
            )

        try:
            with open(absolute_path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as error:
            raise InvalidAuthorityShardError(
                f"Failed to read shard file {shard_path}: {error}"
            ) from error

        if not content.strip():
            # Empty shard is valid (no blocks)
            return cls(path=shard_path, blocks=[])

        try:
            data = load_yaml_text(content)
        except Exception as error:
            raise InvalidAuthorityShardError(
                f"Invalid YAML in shard file {shard_path}: {error}"
            ) from error

        if data is None:
            return cls(path=shard_path, blocks=[])

        # Validate shard structure
        if not isinstance(data, dict):
            raise InvalidAuthorityShardError(
                f"Shard file must be a dictionary, got {type(data).__name__}"
            )

        # Ensure only blocks is present
        for key in data:
            if key != "blocks":
                raise InvalidAuthorityShardError(
                    f"Shard file {shard_path} must contain only 'blocks', "
                    f"found top-level key '{key}'. "
                    f"Shards must not contain project, policy, authority, or includes."
                )

        blocks = data.get("blocks", [])

        if not isinstance(blocks, list):
            raise InvalidAuthorityShardError(
                f"Shard 'blocks' must be a list, got {type(blocks).__name__}"
            )

        return cls(path=shard_path, blocks=blocks)

    def save(self, project_root: Path) -> None:
        """Save the shard file to the project root.

        Args:
            project_root: The project root directory.

        Raises:
            InvalidAuthorityShardError: If the shard is invalid or cannot be saved.
        """
        # Re-validate before saving
        self._validate()

        # Resolve shard path relative to project root
        absolute_path = project_root / self.path
        ensure_blueprint_can_be_written(project_root=project_root)

        # Ensure directory exists
        absolute_path.parent.mkdir(parents=True, exist_ok=True)

        # Prepare shard data
        shard_data = {"blocks": self._blocks}

        # Write YAML with deterministic ordering
        rendered = dump_yaml_data(shard_data, sort_keys=False, allow_unicode=True)

        try:
            absolute_path.write_text(rendered, encoding="utf-8")
        except OSError as error:
            raise InvalidAuthorityShardError(
                f"Failed to write shard file {self.path}: {error}"
            ) from error

    def set_blocks(self, blocks: list[dict[str, Any]]) -> None:
        """Set the blocks for this shard.

        Args:
            blocks: List of block dictionaries.
        """
        self._blocks = blocks
        self._validate()

    def get_blocks(self) -> list[dict[str, Any]]:
        """Get the blocks in this shard.

        Returns:
            List of block dictionaries.
        """
        return self._blocks.copy()

    def is_empty(self) -> bool:
        """Check if this shard has no blocks.

        Returns:
            True if the shard is empty, False otherwise.
        """
        return len(self._blocks) == 0

    def contains_block_id(self, block_id: str) -> bool:
        """Check if this shard contains a block with the given ID.

        Args:
            block_id: The block ID to check for.

        Returns:
            True if the shard contains the block, False otherwise.
        """
        for block in self._blocks:
            if isinstance(block, dict) and block.get("id") == block_id:
                return True
        return False

    def remove_block(self, block_id: str) -> dict[str, Any] | None:
        """Remove a block from this shard by ID.

        Args:
            block_id: The block ID to remove.

        Returns:
            The removed block dictionary, or None if not found.
        """
        for i, block in enumerate(self._blocks):
            if isinstance(block, dict) and block.get("id") == block_id:
                removed = self._blocks.pop(i)
                return removed
        return None

    def add_block(self, block: dict[str, Any]) -> None:
        """Add a block to this shard.

        Args:
            block: The block dictionary to add.
        """
        self._blocks.append(block)
        self._validate()

    def sort_blocks(self) -> None:
        """Sort blocks in the same order every time."""
        def sort_key(block: dict[str, Any]) -> tuple:
            """Generate sort key for a block."""
            domain = block.get("domain") or ""
            code = block.get("code") or {}
            path = code.get("path") or ""
            start_line = code.get("start_line") or 0
            name = block.get("name") or ""
            block_id = block.get("id") or ""

            return (
                str(domain).lower(),
                str(path).lower(),
                int(start_line) if start_line else 0,
                str(name).lower(),
                str(block_id).lower(),
            )

        self._blocks.sort(key=sort_key)
