"""Authority package for BPFW blueprint files.

This package provides loading, validation, persistence, layout planning, and the
Blueprint Engine used to apply approved mechanical changes under ``bpfw/``.
"""

from bpfw.authority.blueprint_engine import (
    BlueprintChangeKind,
    BlueprintChangePreview,
    BlueprintChangeRequest,
    BlueprintChangeResult,
    BlueprintChangeSource,
    BlueprintEngine,
    MechanicalChangeEvidence,
)
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
from bpfw.authority.layout import (
    BlockPlacementChange,
    BlueprintLayoutPlan,
    BlueprintLayoutPlanner,
)
from bpfw.authority.persistence import AuthorityPersistenceEngine, AuthorityPersistenceResult
from bpfw.authority.repository import AuthorityRepository
from bpfw.authority.shard import AuthorityShard, BlockOrigin
from bpfw.authority.sharding import ShardDecisionEngine

__all__ = [
    "AuthorityError",
    "InvalidAuthorityIndexError",
    "InvalidAuthorityShardError",
    "DuplicateBlockIdError",
    "DuplicateCodeDeclarationError",
    "InvalidShardPathError",
    "MissingShardError",
    "ShardDriftError",
    "AuthorityIndex",
    "BlockOrigin",
    "AuthorityShard",
    "AuthorityDocument",
    "ShardDecisionEngine",
    "AuthorityRepository",
    "AuthorityPersistenceResult",
    "AuthorityPersistenceEngine",
    "BlockPlacementChange",
    "BlueprintLayoutPlan",
    "BlueprintLayoutPlanner",
    "BlueprintEngine",
    "BlueprintChangeKind",
    "BlueprintChangePreview",
    "BlueprintChangeRequest",
    "BlueprintChangeResult",
    "BlueprintChangeSource",
    "MechanicalChangeEvidence",
]
