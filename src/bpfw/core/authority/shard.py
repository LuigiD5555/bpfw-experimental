"""PURPOSE authority shard for BPFW block storage
DOMAIN  blueprint files
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bpfw.core.authority.errors import InvalidAuthorityShardError
from bpfw.core.catalog.access_control import ensure_blueprint_can_be_written
from bpfw.core.yaml_io import dump_yaml_data, load_yaml_text


@dataclass(frozen=True)
class BlockOrigin:
    """PURPOSE track which shard a block originated from
    DOMAIN  blueprint files
    """

    block_id: str
    shard_path: Path  # Project-relative path


class AuthorityShard:
    """PURPOSE store information about a single shard file containing blocks
    DOMAIN  blueprint files
    """

    def __init__(self, path: Path, blocks: list[dict[str, Any]]) -> None:
        """PURPOSE set up the authority shard
        DOMAIN  blueprint files
        """
        self.path = path
        self._blocks = blocks
        self._validate()

    def _validate(self) -> None:
        """PURPOSE check the shard structure
        DOMAIN  blueprint files
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
        """PURPOSE read a shard file from the project root
        DOMAIN  blueprint files
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
        """PURPOSE save the shard file to the project root
        DOMAIN  blueprint files
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
        """PURPOSE set the blocks for this shard
        DOMAIN  blueprint files
        """
        self._blocks = blocks
        self._validate()

    def get_blocks(self) -> list[dict[str, Any]]:
        """PURPOSE get the blocks in this shard
        DOMAIN  blueprint files
        """
        return self._blocks.copy()

    def is_empty(self) -> bool:
        """PURPOSE check if this shard has no blocks
        DOMAIN  blueprint files
        """
        return len(self._blocks) == 0

    def block_count(self) -> int:
        """PURPOSE get the number of blocks in this shard
        DOMAIN  blueprint files
        """
        return len(self._blocks)

    def contains_block_id(self, block_id: str) -> bool:
        """PURPOSE check if this shard contains a block with the given ID
        DOMAIN  blueprint files
        """
        for block in self._blocks:
            if isinstance(block, dict) and block.get("id") == block_id:
                return True
        return False

    def remove_block(self, block_id: str) -> dict[str, Any] | None:
        """PURPOSE remove a block from this shard by ID
        DOMAIN  blueprint files
        """
        for i, block in enumerate(self._blocks):
            if isinstance(block, dict) and block.get("id") == block_id:
                removed = self._blocks.pop(i)
                return removed
        return None

    def add_block(self, block: dict[str, Any]) -> None:
        """PURPOSE add a block to this shard
        DOMAIN  blueprint files
        """
        self._blocks.append(block)
        self._validate()

    def sort_blocks(self) -> None:
        """PURPOSE sort blocks stableally
                DOMAIN  blueprint files
                """
        def sort_key(block: dict[str, Any]) -> tuple:
            """PURPOSE generate sort key for a block
            DOMAIN  blueprint files
            """
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
