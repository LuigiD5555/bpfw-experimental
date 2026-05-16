"""Authority-specific exceptions for BPFW sharded blueprint system."""


class AuthorityError(Exception):
    """Base exception for all authority-related errors."""
    pass


class InvalidAuthorityIndexError(AuthorityError):
    """Raised when the root blueprint.yaml is invalid."""
    pass


class InvalidAuthorityShardError(AuthorityError):
    """Raised when a shard file is invalid or cannot be parsed."""
    pass


class DuplicateBlockIdError(AuthorityError):
    """Raised when duplicate block IDs are detected across shards."""
    pass


class DuplicateCodeDeclarationError(AuthorityError):
    """Raised when duplicate code declarations are detected across shards."""
    pass


class InvalidShardPathError(AuthorityError):
    """Raised when a shard path is invalid or outside allowed directory."""
    pass


class MissingShardError(AuthorityError):
    """Raised when a referenced shard file does not exist."""
    pass


class ShardDriftError(AuthorityError):
    """Raised when blocks are in wrong shards based on current strategy."""
    pass