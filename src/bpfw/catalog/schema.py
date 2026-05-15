"""Canonical blueprint terminology helpers."""

from typing import Any, Dict, List

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


def get_blocks(blueprint_data: Dict[str, Any]) -> List[Any]:
    """Return declared blocks from canonical blueprint data."""

    blocks = blueprint_data.get(CANONICAL_BLOCKS_KEY)
    if isinstance(blocks, list):
        return blocks
    return []


def set_blocks(blueprint_data: Dict[str, Any], blocks: List[Dict[str, Any]]) -> None:
    """Set canonical blocks on blueprint data."""

    blueprint_data[CANONICAL_BLOCKS_KEY] = blocks


def get_purpose(block: Dict[str, Any]) -> Any:
    """Return a block purpose from canonical blueprint data."""

    return block.get(CANONICAL_PURPOSE_KEY)


def set_purpose(block: Dict[str, Any], value: Any) -> None:
    """Set the canonical purpose key on a block."""

    if isinstance(value, str):
        value = " ".join(value.strip().lower().split())
    block[CANONICAL_PURPOSE_KEY] = value


def get_status(block: Dict[str, Any]) -> Any:
    """Return a block status from canonical blueprint data."""

    return block.get(CANONICAL_STATUS_KEY)


def set_status(block: Dict[str, Any], value: Any) -> None:
    """Set the canonical status key on a block."""

    block[CANONICAL_STATUS_KEY] = value


def get_code(block: Dict[str, Any]) -> Dict[str, Any]:
    """Return canonical code metadata from a block."""

    code = block.get(CANONICAL_CODE_KEY)
    if isinstance(code, dict):
        return code
    return {}


def set_code(block: Dict[str, Any], value: Dict[str, Any]) -> None:
    """Set canonical code metadata on a block."""

    block[CANONICAL_CODE_KEY] = value


def get_kind(code: Dict[str, Any]) -> Any:
    """Return canonical code kind metadata."""

    return code.get(CANONICAL_KIND_KEY)


def set_kind(code: Dict[str, Any], value: Any) -> None:
    """Set canonical code kind metadata."""

    code[CANONICAL_KIND_KEY] = value


def get_connections(block: Dict[str, Any]) -> List[Any]:
    """Return canonical block connections."""

    connections = block.get(CANONICAL_CONNECTIONS_KEY)
    if isinstance(connections, list):
        return connections
    return []


def get_connection_meaning(connection: Dict[str, Any]) -> Any:
    """Return canonical connection meaning metadata."""

    return connection.get(CANONICAL_MEANING_KEY)


def get_uniqueness(block: Dict[str, Any]) -> Dict[str, Any]:
    """Return canonical uniqueness metadata from a block."""

    uniqueness = block.get(CANONICAL_UNIQUENESS_KEY)
    if isinstance(uniqueness, dict):
        return uniqueness
    return {}


def get_allowed_statuses(policy: Dict[str, Any]) -> List[str]:
    """Return canonical allowed statuses from policy metadata."""

    statuses = policy.get(CANONICAL_ALLOWED_STATUSES_KEY)
    if isinstance(statuses, list):
        return [str(status) for status in statuses]
    return list(DEFAULT_ALLOWED_STATUSES)


def get_one_active_block_per_purpose(policy: Dict[str, Any]) -> bool:
    """Return the canonical duplicate-active-purpose policy value."""

    value = policy.get(CANONICAL_ONE_ACTIVE_PURPOSE_KEY)
    if isinstance(value, bool):
        return value
    return True
