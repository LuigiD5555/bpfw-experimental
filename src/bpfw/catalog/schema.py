"""Canonical blueprint terminology helpers."""

from typing import Any, Callable, Dict, List

CANONICAL_BLOCKS_KEY = "blocks"
CANONICAL_PURPOSE_KEY = "purpose"
CANONICAL_STATUS_KEY = "status"
CANONICAL_CODE_KEY = "code"
CANONICAL_KIND_KEY = "kind"
CANONICAL_CONNECTIONS_KEY = "connections"
CANONICAL_MEANING_KEY = "meaning"
CANONICAL_UNIQUENESS_KEY = "uniqueness"
CANONICAL_ALLOWED_STATUSES_KEY = "allowed_statuses"
CANONICAL_ONE_ACTIVE_PURPOSE_KEY = "one_active_block_per_purpose"

DEFAULT_ALLOWED_STATUSES = ["active", "experimental", "legacy", "deprecated"]


class BlueprintSchema:
    """Consolidated access to canonical blueprint structure.
    
    Provides getters and setters for canonical blueprint fields, reducing
    boilerplate and ensuring consistency across the codebase.
    """

    # ---------------------------------------------------------------------------
    # Internal descriptors
    # ---------------------------------------------------------------------------

    class _FieldAccessor:
        """Descriptor that generates a getter function for a canonical key."""

        def __init__(
            self,
            key: str,
            *,
            expect_type: type | None = None,
            default: Any = None,
            coerce: Callable[[Any], Any] | None = None,
        ) -> None:
            self._key = key
            self._expect_type = expect_type
            self._default = default
            self._coerce = coerce

        def __call__(self, data: Dict[str, Any]) -> Any:
            value = data.get(self._key)
            if self._expect_type is not None:
                if isinstance(value, self._expect_type):
                    if self._coerce is not None:
                        return self._coerce(value)
                    return value
                return self._default if self._default is not None else (
                    [] if self._expect_type is list else {} if self._expect_type is dict else None
                )
            return value

    class _FieldSetter:
        """Descriptor that generates a setter function for a canonical key."""

        def __init__(
            self,
            key: str,
            *,
            coerce: Callable[[Any], Any] | None = None,
        ) -> None:
            self._key = key
            self._coerce = coerce

        def __call__(self, data: Dict[str, Any], value: Any) -> None:
            if self._coerce is not None:
                value = self._coerce(value)
            data[self._key] = value

    # ---------------------------------------------------------------------------
    # Instance-based accessors
    # ---------------------------------------------------------------------------

    def __init__(self) -> None:
        self._get_blocks = self._FieldAccessor(CANONICAL_BLOCKS_KEY, expect_type=list, default=[])
        self._get_purpose = self._FieldAccessor(CANONICAL_PURPOSE_KEY)
        self._get_status = self._FieldAccessor(CANONICAL_STATUS_KEY)
        self._get_code = self._FieldAccessor(CANONICAL_CODE_KEY, expect_type=dict, default={})
        self._get_kind = self._FieldAccessor(CANONICAL_KIND_KEY)
        self._get_connections = self._FieldAccessor(CANONICAL_CONNECTIONS_KEY, expect_type=list, default=[])
        self._get_connection_meaning = self._FieldAccessor(CANONICAL_MEANING_KEY)
        self._get_uniqueness = self._FieldAccessor(CANONICAL_UNIQUENESS_KEY, expect_type=dict, default={})
        self._get_allowed_statuses = self._FieldAccessor(
            CANONICAL_ALLOWED_STATUSES_KEY,
            expect_type=list,
            default=DEFAULT_ALLOWED_STATUSES,
            coerce=lambda statuses: [str(status) for status in statuses],
        )
        self._get_one_active_block_per_purpose = self._FieldAccessor(
            CANONICAL_ONE_ACTIVE_PURPOSE_KEY,
            expect_type=bool,
            default=True,
        )

        def _coerce_purpose(value: Any) -> Any:
            if isinstance(value, str):
                return " ".join(value.strip().lower().split())
            return value

        self._set_purpose = self._FieldSetter(CANONICAL_PURPOSE_KEY, coerce=_coerce_purpose)
        self._set_status = self._FieldSetter(CANONICAL_STATUS_KEY)
        self._set_code = self._FieldSetter(CANONICAL_CODE_KEY)
        self._set_kind = self._FieldSetter(CANONICAL_KIND_KEY)

    # ---------------------------------------------------------------------------
    # Blueprint-level methods
    # ---------------------------------------------------------------------------

    def get_blocks(self, blueprint_data: Dict[str, Any]) -> List[Any]:
        """Return declared blocks from canonical blueprint data."""
        return self._get_blocks(blueprint_data)

    def set_blocks(self, blueprint_data: Dict[str, Any], blocks: List[Dict[str, Any]]) -> None:
        """Set canonical blocks on blueprint data."""
        blueprint_data[CANONICAL_BLOCKS_KEY] = blocks

    # ---------------------------------------------------------------------------
    # Block-level methods
    # ---------------------------------------------------------------------------

    def get_purpose(self, block: Dict[str, Any]) -> Any:
        """Return a block purpose from canonical blueprint data."""
        return self._get_purpose(block)

    def set_purpose(self, block: Dict[str, Any], value: Any) -> None:
        """Set the canonical purpose key on a block."""
        self._set_purpose(block, value)

    def get_status(self, block: Dict[str, Any]) -> Any:
        """Return a block status from canonical blueprint data."""
        return self._get_status(block)

    def set_status(self, block: Dict[str, Any], value: Any) -> None:
        """Set the canonical status key on a block."""
        self._set_status(block, value)

    # ---------------------------------------------------------------------------
    # Code metadata methods
    # ---------------------------------------------------------------------------

    def get_code(self, block: Dict[str, Any]) -> Dict[str, Any]:
        """Return canonical code metadata from a block."""
        return self._get_code(block)

    def set_code(self, block: Dict[str, Any], value: Dict[str, Any]) -> None:
        """Set canonical code metadata on a block."""
        self._set_code(block, value)

    def get_kind(self, code: Dict[str, Any]) -> Any:
        """Return canonical code kind metadata."""
        return self._get_kind(code)

    def set_kind(self, code: Dict[str, Any], value: Any) -> None:
        """Set canonical code kind metadata."""
        self._set_kind(code, value)

    # ---------------------------------------------------------------------------
    # Connection methods
    # ---------------------------------------------------------------------------

    def get_connections(self, block: Dict[str, Any]) -> List[Any]:
        """Return canonical block connections."""
        return self._get_connections(block)

    def get_connection_meaning(self, connection: Dict[str, Any]) -> Any:
        """Return canonical connection meaning metadata."""
        return self._get_connection_meaning(connection)

    # ---------------------------------------------------------------------------
    # Policy and uniqueness methods
    # ---------------------------------------------------------------------------

    def get_uniqueness(self, block: Dict[str, Any]) -> Dict[str, Any]:
        """Return canonical uniqueness metadata from a block."""
        return self._get_uniqueness(block)

    def get_allowed_statuses(self, policy: Dict[str, Any]) -> List[str]:
        """Return canonical allowed statuses from policy metadata."""
        return self._get_allowed_statuses(policy)

    def get_one_active_block_per_purpose(self, policy: Dict[str, Any]) -> bool:
        """Return the canonical duplicate-active-purpose policy value."""
        return self._get_one_active_block_per_purpose(policy)


# ---------------------------------------------------------------------------
# Global instance for convenience
# ---------------------------------------------------------------------------

schema = BlueprintSchema()

# ---------------------------------------------------------------------------
# Convenience module-level functions (deprecated, kept for backward compatibility)
# ---------------------------------------------------------------------------

def get_blocks(blueprint_data: Dict[str, Any]) -> List[Any]:
    """Return declared blocks from canonical blueprint data."""
    return schema.get_blocks(blueprint_data)


def set_blocks(blueprint_data: Dict[str, Any], blocks: List[Dict[str, Any]]) -> None:
    """Set canonical blocks on blueprint data."""
    return schema.set_blocks(blueprint_data, blocks)


def get_purpose(block: Dict[str, Any]) -> Any:
    """Return a block purpose from canonical blueprint data."""
    return schema.get_purpose(block)


def set_purpose(block: Dict[str, Any], value: Any) -> None:
    """Set the canonical purpose key on a block."""
    return schema.set_purpose(block, value)


def get_status(block: Dict[str, Any]) -> Any:
    """Return a block status from canonical blueprint data."""
    return schema.get_status(block)


def set_status(block: Dict[str, Any], value: Any) -> None:
    """Set the canonical status key on a block."""
    return schema.set_status(block, value)


def get_code(block: Dict[str, Any]) -> Dict[str, Any]:
    """Return canonical code metadata from a block."""
    return schema.get_code(block)


def set_code(block: Dict[str, Any], value: Dict[str, Any]) -> None:
    """Set canonical code metadata on a block."""
    return schema.set_code(block, value)


def get_kind(code: Dict[str, Any]) -> Any:
    """Return canonical code kind metadata."""
    return schema.get_kind(code)


def set_kind(code: Dict[str, Any], value: Any) -> None:
    """Set canonical code kind metadata."""
    return schema.set_kind(code, value)


def get_connections(block: Dict[str, Any]) -> List[Any]:
    """Return canonical block connections."""
    return schema.get_connections(block)


def get_connection_meaning(connection: Dict[str, Any]) -> Any:
    """Return canonical connection meaning metadata."""
    return schema.get_connection_meaning(connection)


def get_uniqueness(block: Dict[str, Any]) -> Dict[str, Any]:
    """Return canonical uniqueness metadata from a block."""
    return schema.get_uniqueness(block)


def get_allowed_statuses(policy: Dict[str, Any]) -> List[str]:
    """Return canonical allowed statuses from policy metadata."""
    return schema.get_allowed_statuses(policy)


def get_one_active_block_per_purpose(policy: Dict[str, Any]) -> bool:
    """Return the canonical duplicate-active-purpose policy value."""
    return schema.get_one_active_block_per_purpose(policy)