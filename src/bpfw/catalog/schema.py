"""Canonical blueprint terminology helpers.

BPFW writes the canonical block terminology while still accepting legacy
catalog keys produced by earlier MVP builds.
"""

from typing import Any, Dict, Iterable, List

CANONICAL_BLOCKS_KEY = "blocks"
LEGACY_BLOCKS_KEY = "responsibilities"

CANONICAL_PURPOSE_KEY = "purpose"
LEGACY_PURPOSE_KEY = "intent"

CANONICAL_STATUS_KEY = "status"
LEGACY_STATUS_KEY = "lifecycle"

CANONICAL_CODE_KEY = "code"
LEGACY_CODE_KEY = "location"

CANONICAL_KIND_KEY = "kind"
LEGACY_KIND_KEY = "symbol_type"

CANONICAL_CONNECTIONS_KEY = "connections"
LEGACY_CONNECTIONS_KEY = "related_code"

CANONICAL_MEANING_KEY = "meaning"
LEGACY_MEANING_KEY = "relationship"

CANONICAL_UNIQUENESS_KEY = "uniqueness"
LEGACY_UNIQUENESS_KEY = "duplicate_policy"

CANONICAL_ALLOWED_STATUSES_KEY = "allowed_statuses"
LEGACY_ALLOWED_STATUSES_KEY = "allowed_lifecycles"

CANONICAL_ONE_ACTIVE_PURPOSE_KEY = "one_active_block_per_purpose"
LEGACY_ONE_ACTIVE_PURPOSE_KEY = "single_active_per_intent"


def get_blocks(blueprint_data: Dict[str, Any]) -> List[Any]:
    """Return declared blocks from canonical or legacy blueprint data."""
    blocks = blueprint_data.get(CANONICAL_BLOCKS_KEY)
    if isinstance(blocks, list):
        return blocks
    legacy_blocks = blueprint_data.get(LEGACY_BLOCKS_KEY)
    if isinstance(legacy_blocks, list):
        return legacy_blocks
    return []


def set_blocks(blueprint_data: Dict[str, Any], blocks: List[Dict[str, Any]]) -> None:
    """Set canonical blocks and remove the legacy responsibilities key."""
    blueprint_data[CANONICAL_BLOCKS_KEY] = blocks
    blueprint_data.pop(LEGACY_BLOCKS_KEY, None)


def get_purpose(block: Dict[str, Any]) -> Any:
    """Return a block purpose using canonical or legacy keys."""
    if CANONICAL_PURPOSE_KEY in block:
        return block.get(CANONICAL_PURPOSE_KEY)
    return block.get(LEGACY_PURPOSE_KEY)


def set_purpose(block: Dict[str, Any], value: Any) -> None:
    """Set the canonical purpose key and remove the legacy intent key."""

    if isinstance(value, str):
        value = " ".join(value.strip().lower().split())
    block[CANONICAL_PURPOSE_KEY] = value
    block.pop(LEGACY_PURPOSE_KEY, None)


def get_status(block: Dict[str, Any]) -> Any:
    """Return a block status using canonical or legacy keys."""
    if CANONICAL_STATUS_KEY in block:
        return block.get(CANONICAL_STATUS_KEY)
    return block.get(LEGACY_STATUS_KEY)


def set_status(block: Dict[str, Any], value: Any) -> None:
    """Set the canonical status key and remove the legacy lifecycle key."""
    block[CANONICAL_STATUS_KEY] = value
    block.pop(LEGACY_STATUS_KEY, None)


def get_code(block: Dict[str, Any]) -> Dict[str, Any]:
    """Return code metadata using canonical or legacy keys."""
    code = block.get(CANONICAL_CODE_KEY)
    if isinstance(code, dict):
        return code
    legacy_code = block.get(LEGACY_CODE_KEY)
    if isinstance(legacy_code, dict):
        return legacy_code
    return {}


def set_code(block: Dict[str, Any], value: Dict[str, Any]) -> None:
    """Set canonical code metadata and remove legacy location metadata."""
    block[CANONICAL_CODE_KEY] = value
    block.pop(LEGACY_CODE_KEY, None)


def get_kind(code: Dict[str, Any]) -> Any:
    """Return code kind using canonical or legacy keys."""
    if CANONICAL_KIND_KEY in code:
        return code.get(CANONICAL_KIND_KEY)
    return code.get(LEGACY_KIND_KEY)


def set_kind(code: Dict[str, Any], value: Any) -> None:
    """Set canonical kind and remove the legacy symbol_type key."""
    code[CANONICAL_KIND_KEY] = value
    code.pop(LEGACY_KIND_KEY, None)


def get_connections(block: Dict[str, Any]) -> List[Any]:
    """Return block connections using canonical or legacy keys."""
    connections = block.get(CANONICAL_CONNECTIONS_KEY)
    if isinstance(connections, list):
        return connections
    legacy_connections = block.get(LEGACY_CONNECTIONS_KEY)
    if isinstance(legacy_connections, list):
        return legacy_connections
    return []


def get_connection_meaning(connection: Dict[str, Any]) -> Any:
    """Return connection meaning using canonical or legacy keys."""
    if CANONICAL_MEANING_KEY in connection:
        return connection.get(CANONICAL_MEANING_KEY)
    return connection.get(LEGACY_MEANING_KEY)


def get_uniqueness(block: Dict[str, Any]) -> Dict[str, Any]:
    """Return uniqueness metadata using canonical or legacy keys."""
    uniqueness = block.get(CANONICAL_UNIQUENESS_KEY)
    if isinstance(uniqueness, dict):
        return uniqueness
    legacy_uniqueness = block.get(LEGACY_UNIQUENESS_KEY)
    if isinstance(legacy_uniqueness, dict):
        return legacy_uniqueness
    return {}


def get_allowed_statuses(policy: Dict[str, Any]) -> List[str]:
    """Return allowed statuses using canonical or legacy policy keys."""
    statuses = policy.get(CANONICAL_ALLOWED_STATUSES_KEY)
    if isinstance(statuses, list):
        return [str(status) for status in statuses]
    legacy_statuses = policy.get(LEGACY_ALLOWED_STATUSES_KEY)
    if isinstance(legacy_statuses, list):
        return [str(status) for status in legacy_statuses]
    return ["active", "experimental", "legacy", "deprecated"]


def get_one_active_block_per_purpose(policy: Dict[str, Any]) -> bool:
    """Return duplicate-active-purpose policy from canonical or legacy keys."""
    value = policy.get(CANONICAL_ONE_ACTIVE_PURPOSE_KEY)
    if isinstance(value, bool):
        return value
    legacy_value = policy.get(LEGACY_ONE_ACTIVE_PURPOSE_KEY)
    if isinstance(legacy_value, bool):
        return legacy_value
    return True


def normalize_block(block: Dict[str, Any]) -> Dict[str, Any]:
    """Return a canonical block dictionary from canonical or legacy input."""
    code = dict(get_code(block))
    if LEGACY_KIND_KEY in code and CANONICAL_KIND_KEY not in code:
        code[CANONICAL_KIND_KEY] = code.get(LEGACY_KIND_KEY)
    code.pop(LEGACY_KIND_KEY, None)

    connections = []
    for connection in get_connections(block):
        if not isinstance(connection, dict):
            continue
        normalized_connection = dict(connection)
        if LEGACY_MEANING_KEY in normalized_connection and CANONICAL_MEANING_KEY not in normalized_connection:
            normalized_connection[CANONICAL_MEANING_KEY] = normalized_connection.get(LEGACY_MEANING_KEY)
        normalized_connection.pop(LEGACY_MEANING_KEY, None)
        connections.append(normalized_connection)

    uniqueness = dict(get_uniqueness(block))
    if "forbidden_active_duplicates" in uniqueness and "forbid_active_duplicates" not in uniqueness:
        uniqueness["forbid_active_duplicates"] = uniqueness.get("forbidden_active_duplicates")
    uniqueness.pop("forbidden_active_duplicates", None)

    normalized = dict(block)
    normalized[CANONICAL_PURPOSE_KEY] = get_purpose(block)
    normalized[CANONICAL_STATUS_KEY] = get_status(block)
    normalized[CANONICAL_CODE_KEY] = code
    normalized[CANONICAL_CONNECTIONS_KEY] = connections
    if uniqueness:
        normalized[CANONICAL_UNIQUENESS_KEY] = uniqueness

    for legacy_key in (
        LEGACY_PURPOSE_KEY,
        LEGACY_STATUS_KEY,
        LEGACY_CODE_KEY,
        LEGACY_CONNECTIONS_KEY,
        LEGACY_UNIQUENESS_KEY,
    ):
        normalized.pop(legacy_key, None)

    return normalized


def normalize_blueprint(blueprint_data: Dict[str, Any]) -> Dict[str, Any]:
    """Return blueprint data using canonical block terminology."""
    normalized = dict(blueprint_data)
    blocks = [normalize_block(block) for block in get_blocks(blueprint_data) if isinstance(block, dict)]
    set_blocks(normalized, blocks)

    policy = normalized.get("policy")
    if isinstance(policy, dict):
        policy = dict(policy)
        if LEGACY_ALLOWED_STATUSES_KEY in policy and CANONICAL_ALLOWED_STATUSES_KEY not in policy:
            policy[CANONICAL_ALLOWED_STATUSES_KEY] = policy.get(LEGACY_ALLOWED_STATUSES_KEY)
        if LEGACY_ONE_ACTIVE_PURPOSE_KEY in policy and CANONICAL_ONE_ACTIVE_PURPOSE_KEY not in policy:
            policy[CANONICAL_ONE_ACTIVE_PURPOSE_KEY] = policy.get(LEGACY_ONE_ACTIVE_PURPOSE_KEY)
        policy.pop(LEGACY_ALLOWED_STATUSES_KEY, None)
        policy.pop(LEGACY_ONE_ACTIVE_PURPOSE_KEY, None)
        normalized["policy"] = policy

    return normalized
