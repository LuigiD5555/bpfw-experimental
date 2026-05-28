"""PURPOSE authority-specific exceptions for BPFW sharded blueprint system
DOMAIN  blueprint files
"""


class AuthorityError(Exception):
    """PURPOSE base exception for all authority-related errors
    DOMAIN  blueprint files
    """
    pass


class InvalidAuthorityIndexError(AuthorityError):
    """PURPOSE raised when the root blueprint.yaml is invalid
    DOMAIN  blueprint files
    """
    pass


class InvalidAuthorityShardError(AuthorityError):
    """PURPOSE raised when a shard file is invalid or cannot be parsed
    DOMAIN  blueprint files
    """
    pass


class DuplicateBlockIdError(AuthorityError):
    """PURPOSE raised when duplicate block IDs are detected across shards
    DOMAIN  blueprint files
    """
    pass


class DuplicateCodeDeclarationError(AuthorityError):
    """PURPOSE raised when duplicate code declarations are detected across shards
    DOMAIN  blueprint files
    """
    pass


class InvalidShardPathError(AuthorityError):
    """PURPOSE raised when a shard path is invalid or outside allowed directory
    DOMAIN  blueprint files
    """
    pass


class MissingShardError(AuthorityError):
    """PURPOSE raised when a referenced shard file does not exist
    DOMAIN  blueprint files
    """
    pass


class ShardDriftError(AuthorityError):
    """PURPOSE raised when blocks are in wrong shards based on strategy
    DOMAIN  blueprint files
    """
    pass