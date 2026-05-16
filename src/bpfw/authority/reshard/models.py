"""Shared data models for reshard operations."""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class BlockMove:
    """Represent a block move between shards."""

    block_id: str
    from_shard: Path
    to_shard: Path
    reason: str
