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


# ---------------------------------------------------------------------------
# Descriptor / factory for reducing repetitive accessors
# ---------------------------------------------------------------------------

class _FieldAccessor:
    """Descriptor that generates a getter function for a canonical key.

    Reduces the repetitive pattern of ``data.get(KEY)`` with optional
    type-checking and fallback defaults.
    """

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
        """Retrieve the field value from *data*."""
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
    """Descriptor that generates a setter function for a canonical key.

    Reduces the repetitive pattern of ``data[KEY] = value`` with optional
    value coercion.
    """

    def __init__(
        self,
        key: str,
        *,
        coerce: Callable[[Any], Any] | None = None,
    ) -> None:
        self._key = key
        self._coerce = coerce

    def __call__(self, data: Dict[str, Any], value: Any) -> None:
        """Set the field value on *data*."""
        if self._coerce is not None:
            value = self._coerce(value)
        data[self._key] = value


# ---------------------------------------------------------------------------
# Public accessor functions (generated via descriptors)
# ---------------------------------------------------------------------------

_get_blocks = _FieldAccessor(CANONICAL_BLOCKS_KEY, expect_type=list, default=[])
_get_purpose = _FieldAccessor(CANONICAL_PURPOSE_KEY)
_get_status = _FieldAccessor(CANONICAL_STATUS_KEY)
_get_code = _FieldAccessor(CANONICAL_CODE_KEY, expect_type=dict, default={})
_get_kind = _FieldAccessor(CANONICAL_KIND_KEY)
_get_connections = _FieldAccessor(CANONICAL_CONNECTIONS_KEY, expect_type=list, default=[])
_get_connection_meaning = _FieldAccessor(CANONICAL_MEANING_KEY)
_get_uniqueness = _FieldAccessor(CANONICAL_UNIQUENESS_KEY, expect_type=dict, default={})
_get_allowed_statuses = _FieldAccessor(
    CANONICAL_ALLOWED_STATUSES_KEY,
    expect_type=list,
    default=DEFAULT_ALLOWED_STATUSES,
    coerce=lambda statuses: [str(status) for status in statuses],
)
_get_one_active_block_per_purpose = _FieldAccessor(
    CANONICAL_ONE_ACTIVE_PURPOSE_KEY,
    expect_type=bool,
    default=True,
)


def get_blocks(blueprint_data: Dict[str, Any]) -> List[Any]:
    """Return declared blocks from canonical blueprint data."""
    return _get_blocks(blueprint_data)


def set_blocks(blueprint_data: Dict[str, Any], blocks: List[Dict[str, Any]]) -> None:
    """Set canonical blocks on blueprint data."""
    blueprint_data[CANONICAL_BLOCKS_KEY] = blocks


def get_purpose(block: Dict[str, Any]) -> Any:
    """Return a block purpose from canonical blueprint data."""
    return _get_purpose(block)


def _coerce_purpose(value: Any) -> Any:
    """Normalize purpose text before storing."""
    if isinstance(value, str):
        return " ".join(value.strip().lower().split())
    return value


_set_purpose = _FieldSetter(CANONICAL_PURPOSE_KEY, coerce=_coerce_purpose)


def set_purpose(block: Dict[str, Any], value: Any) -> None:
    """Set the canonical purpose key on a block."""
    _set_purpose(block, value)


def get_status(block: Dict[str, Any]) -> Any:
    """Return a block status from canonical blueprint data."""
    return _get_status(block)


_set_status = _FieldSetter(CANONICAL_STATUS_KEY)


def set_status(block: Dict[str, Any], value: Any) -> None:
    """Set the canonical status key on a block."""
    _set_status(block, value)


def get_code(block: Dict[str, Any]) -> Dict[str, Any]:
    """Return canonical code metadata from a block."""
    return _get_code(block)


_set_code = _FieldSetter(CANONICAL_CODE_KEY)


def set_code(block: Dict[str, Any], value: Dict[str, Any]) -> None:
    """Set canonical code metadata on a block."""
    _set_code(block, value)


def get_kind(code: Dict[str, Any]) -> Any:
    """Return canonical code kind metadata."""
    return _get_kind(code)


_set_kind = _FieldSetter(CANONICAL_KIND_KEY)


def set_kind(code: Dict[str, Any], value: Any) -> None:
    """Set canonical code kind metadata."""
    _set_kind(code, value)


def get_connections(block: Dict[str, Any]) -> List[Any]:
    """Return canonical block connections."""
    return _get_connections(block)


def get_connection_meaning(connection: Dict[str, Any]) -> Any:
    """Return canonical connection meaning metadata."""
    return _get_connection_meaning(connection)


def get_uniqueness(block: Dict[str, Any]) -> Dict[str, Any]:
    """Return canonical uniqueness metadata from a block."""
    return _get_uniqueness(block)


def get_allowed_statuses(policy: Dict[str, Any]) -> List[str]:
    """Return canonical allowed statuses from policy metadata."""
    return _get_allowed_statuses(policy)


def get_one_active_block_per_purpose(policy: Dict[str, Any]) -> bool:
    """Return the canonical duplicate-active-purpose policy value."""
    return _get_one_active_block_per_purpose(policy)