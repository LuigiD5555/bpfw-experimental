"""PURPOSE authority package for BPFW blueprint files
DOMAIN  blueprint files
"""

from bpfw.core.blueprint_engine import (
    BlueprintChangeKind,
    BlueprintChangePreview,
    BlueprintChangeRequest,
    BlueprintChangeResult,
    BlueprintChangeSource,
    BlueprintEngine,
    MechanicalChangeEvidence,
)
from bpfw.core.authority.document import AuthorityDocument
from bpfw.core.authority.errors import (
    AuthorityError,
    DuplicateBlockIdError,
    DuplicateCodeDeclarationError,
    InvalidAuthorityIndexError,
    InvalidAuthorityShardError,
    InvalidShardPathError,
    MissingShardError,
    ShardDriftError,
)
from bpfw.core.authority.index import AuthorityIndex
from bpfw.core.authority.persistence import AuthorityPersistenceEngine, AuthorityPersistenceResult
from bpfw.core.authority.repository import AuthorityRepository
from bpfw.core.authority.shard import AuthorityShard, BlockOrigin
from bpfw.core.authority.sharding import ShardDecisionEngine

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
    "BlueprintEngine",
    "BlueprintChangeKind",
    "BlueprintChangePreview",
    "BlueprintChangeRequest",
    "BlueprintChangeResult",
    "BlueprintChangeSource",
    "MechanicalChangeEvidence",
]
