"""Authority document for unified in-memory model."""

from pathlib import Path
from typing import Any

from bpfw.authority.index import AuthorityIndex
from bpfw.authority.shard import AuthorityShard


class AuthorityDocument:
    """Unified in-memory model for sharded authority.
    
    This class holds:
    - index: AuthorityIndex (root blueprint.yaml)
    - blueprint_data: dict with version, project, policy, authority, includes, blocks
    - block_origins: dict mapping block_id -> shard_path
    - shards: dict mapping shard_path -> AuthorityShard
    
    The blueprint_data dict has the same shape as the current loaded blueprint,
    so existing integrations continue to work without changes.
    """

    def __init__(
        self,
        index: AuthorityIndex,
        blueprint_data: dict[str, Any],
        block_origins: dict[str, Path],
        shards: dict[Path, AuthorityShard],
    ) -> None:
        """Initialize the authority document.
        
        Args:
            index: The authority index.
            blueprint_data: Unified blueprint data with blocks.
            block_origins: Mapping from block ID to shard path.
            shards: Mapping from shard path to AuthorityShard.
        """
        self.index = index
        self.blueprint_data = blueprint_data
        self.block_origins = block_origins
        self.shards = shards

    def get_blocks(self) -> list[dict[str, Any]]:
        """Get all blocks from the unified blueprint data.
        
        Returns:
            List of block dictionaries.
        """
        blocks = self.blueprint_data.get("blocks")
        if isinstance(blocks, list):
            return blocks.copy()
        return []

    def replace_blocks(self, blocks: list[dict[str, Any]]) -> None:
        """Replace all blocks in the unified blueprint data.
        
        Args:
            blocks: New list of block dictionaries.
        """
        self.blueprint_data["blocks"] = blocks

    def get_origin(self, block_id: str) -> Path | None:
        """Get the shard path for a block ID.
        
        Args:
            block_id: The block ID to look up.
        
        Returns:
            Project-relative shard path, or None if block not found.
        """
        return self.block_origins.get(block_id)

    def get_block(self, block_id: str) -> dict[str, Any] | None:
        """Get a specific block by ID.
        
        Args:
            block_id: The block ID to look up.
        
        Returns:
            Block dictionary, or None if not found.
        """
        for block in self.get_blocks():
            if isinstance(block, dict) and block.get("id") == block_id:
                return block
        return None

    def get_shard_for_block(self, block_id: str) -> AuthorityShard | None:
        """Get the AuthorityShard that contains a block.
        
        Args:
            block_id: The block ID to look up.
        
        Returns:
            AuthorityShard instance, or None if block not found.
        """
        shard_path = self.get_origin(block_id)
        if shard_path is None:
            return None
        return self.get_shard(shard_path)

    def get_shard(self, shard_path: Path) -> AuthorityShard | None:
        """Get an authority shard by its project-relative path.
        
        Args:
            shard_path: Project-relative shard path.
        
        Returns:
            AuthorityShard instance, or None if shard is not loaded.
        """
        return self.shards.get(shard_path)

    def get_blocks_from_shard(self, shard_path: Path) -> list[dict[str, Any]]:
        """Get all blocks from a specific shard.
        
        Args:
            shard_path: Project-relative shard path.
        
        Returns:
            List of block dictionaries from the shard.
        """
        shard = self.get_shard(shard_path)
        if shard is None:
            return []
        return shard.get_blocks()

    def get_shard_blocks(self, shard_path: Path) -> list[dict[str, Any]]:
        """Get all blocks from a specific shard.
        
        Args:
            shard_path: Project-relative shard path.
        
        Returns:
            List of block dictionaries from the shard.
        """
        return self.get_blocks_from_shard(shard_path)

    def get_block_count(self) -> int:
        """Get the total number of blocks.
        
        Returns:
            Total block count.
        """
        return len(self.get_blocks())

    def get_shard_count(self) -> int:
        """Get the number of loaded shards.
        
        Returns:
            Number of shards.
        """
        return len(self.shards)

    def get_shard_paths(self) -> list[Path]:
        """Get all shard paths.
        
        Returns:
            List of project-relative shard paths.
        """
        return list(self.shards.keys())

    def get_included_shard_paths(self) -> list[Path]:
        """Get shard paths from the index includes.
        
        Returns:
            List of project-relative shard paths from includes.
        """
        return self.index.get_includes()

    def get_project_root(self) -> Path:
        """Get the project root directory.
        
        Returns:
            Project root Path.
        """
        return self.index.path.parent.parent

    def get_authority_config(self) -> dict[str, Any]:
        """Get the authority configuration.
        
        Returns:
            Dictionary containing authority configuration.
        """
        return self.index.get_authority_config()
