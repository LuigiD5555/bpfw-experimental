"""Authority sharding engine for BPFW.

This package provides:
- AuthorityIndex: Root blueprint.yaml management
- AuthorityShard: Individual shard file management
- AuthorityDocument: Unified in-memory model
- ShardDecisionEngine: Decide shard placement based on strategy
- AuthorityRepository: Load, validate, and save documents
- AuthorityPersistenceEngine: Handle physical persistence
- AuthorityReshardPlanner: Plan and apply reshard operations
"""

from bpfw.authority.document import AuthorityDocument
from bpfw.authority.errors import (
    AuthorityError,
    DuplicateBlockIdError,
    DuplicateCodeDeclarationError,
    InvalidAuthorityIndexError,
    InvalidAuthorityShardError,
    InvalidShardPathError,
    MissingShardError,
    ShardDriftError,
)
from bpfw.authority.index import AuthorityIndex
from bpfw.authority.persistence import AuthorityPersistenceEngine, AuthorityPersistenceResult, BlockMove
from bpfw.authority.planner import AuthorityReshardPlanner, ReshardPlan
from bpfw.authority.repository import AuthorityRepository
from bpfw.authority.shard import AuthorityShard, BlockOrigin
from bpfw.authority.sharding import ShardDecisionEngine

__all__ = [
    # Errors
    "AuthorityError",
    "InvalidAuthorityIndexError",
    "InvalidAuthorityShardError",
    "DuplicateBlockIdError",
    "DuplicateCodeDeclarationError",
    "InvalidShardPathError",
    "MissingShardError",
    "ShardDriftError",
    # Index
    "AuthorityIndex",
    # Shard
    "BlockOrigin",
    "AuthorityShard",
    # Document
    "AuthorityDocument",
    # Sharding
    "ShardDecisionEngine",
    # Repository
    "AuthorityRepository",
    # Persistence
    "BlockMove",
    "AuthorityPersistenceResult",
    "AuthorityPersistenceEngine",
    # Planner
    "ReshardPlan",
    "AuthorityReshardPlanner",
]