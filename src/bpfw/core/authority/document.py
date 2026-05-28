"""PURPOSE authority document for unified loaded model
DOMAIN  blueprint files
"""

from pathlib import Path
from typing import Any

from bpfw.core.authority.index import AuthorityIndex
from bpfw.core.authority.shard import AuthorityShard


class AuthorityDocument:
    """PURPOSE unified loaded model for sharded authority
    DOMAIN  blueprint files
    """

    def __init__(
        self,
        index: AuthorityIndex,
        blueprint_data: dict[str, Any],
        block_origins: dict[str, Path],
        shards: dict[Path, AuthorityShard],
    ) -> None:
        """PURPOSE set up the authority document
        DOMAIN  blueprint files
        """
        self.index = index
        self.blueprint_data = blueprint_data
        self.block_origins = block_origins
        self.shards = shards

    def get_blocks(self) -> list[dict[str, Any]]:
        """PURPOSE get all blocks from the unified blueprint data
        DOMAIN  blueprint files
        """
        blocks = self.blueprint_data.get("blocks")
        if isinstance(blocks, list):
            return blocks.copy()
        return []

    def replace_blocks(self, blocks: list[dict[str, Any]]) -> None:
        """PURPOSE replace all blocks in the unified blueprint data
        DOMAIN  blueprint files
        """
        self.blueprint_data["blocks"] = blocks

    def get_origin(self, block_id: str) -> Path | None:
        """PURPOSE get the shard path for a block ID
        DOMAIN  blueprint files
        """
        return self.block_origins.get(block_id)

    def get_block(self, block_id: str) -> dict[str, Any] | None:
        """PURPOSE get a specific block by ID
        DOMAIN  blueprint files
        """
        for block in self.get_blocks():
            if isinstance(block, dict) and block.get("id") == block_id:
                return block
        return None

    def get_shard_for_block(self, block_id: str) -> AuthorityShard | None:
        """PURPOSE get the AuthorityShard that contains a block
        DOMAIN  blueprint files
        """
        shard_path = self.get_origin(block_id)
        if shard_path is None:
            return None
        return self.get_shard(shard_path)

    def get_shard(self, shard_path: Path) -> AuthorityShard | None:
        """PURPOSE get an authority shard by its project-relative path
        DOMAIN  blueprint files
        """
        return self.shards.get(shard_path)

    def get_blocks_from_shard(self, shard_path: Path) -> list[dict[str, Any]]:
        """PURPOSE get all blocks from a specific shard
        DOMAIN  blueprint files
        """
        shard = self.get_shard(shard_path)
        if shard is None:
            return []
        return shard.get_blocks()

    def get_block_count(self) -> int:
        """PURPOSE get the total number of blocks
        DOMAIN  blueprint files
        """
        return len(self.get_blocks())

    def get_shard_count(self) -> int:
        """PURPOSE get the number of loaded shards
        DOMAIN  blueprint files
        """
        return len(self.shards)

    def get_shard_paths(self) -> list[Path]:
        """PURPOSE get all shard paths
        DOMAIN  blueprint files
        """
        return list(self.shards.keys())

    def get_included_shard_paths(self) -> list[Path]:
        """PURPOSE get shard paths from the index includes
        DOMAIN  blueprint files
        """
        return self.index.get_includes()

    def get_project_root(self) -> Path:
        """PURPOSE get the project root directory
        DOMAIN  blueprint files
        """
        return self.index.path.parent.parent

    def get_authority_config(self) -> dict[str, Any]:
        """PURPOSE get the authority configuration
        DOMAIN  blueprint files
        """
        return self.index.get_authority_config()
