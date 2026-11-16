"""Authority package for BPFW blueprint files.

Blueprint Engine symbols remain available lazily for backward compatibility,
without creating an authority <-> blueprint_engine import cycle.
"""
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

_BLUEPRINT_EXPORTS = {
    "BlueprintEngine",
    "BlueprintChangeKind",
    "BlueprintChangePreview",
    "BlueprintChangeRequest",
    "BlueprintChangeResult",
    "BlueprintChangeSource",
    "MechanicalChangeEvidence",
}

def __getattr__(name: str):  # noqa: ANN001
    if name in _BLUEPRINT_EXPORTS:
        import bpfw.core.blueprint_engine as blueprint_engine
        return getattr(blueprint_engine, name)
    raise AttributeError(name)

__all__ = [
    "AuthorityError", "InvalidAuthorityIndexError", "InvalidAuthorityShardError",
    "DuplicateBlockIdError", "DuplicateCodeDeclarationError", "InvalidShardPathError",
    "MissingShardError", "ShardDriftError", "AuthorityIndex", "BlockOrigin",
    "AuthorityShard", "AuthorityDocument", "ShardDecisionEngine", "AuthorityRepository",
    "AuthorityPersistenceResult", "AuthorityPersistenceEngine",
    *_BLUEPRINT_EXPORTS,
]
