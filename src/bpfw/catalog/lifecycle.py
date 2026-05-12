"""Status rules for BPFW MVP Catalog Mode.

The constants keep their historical names for compatibility, but user-facing
terminology should call these values statuses.
"""

from typing import Any

LIFECYCLE_ACTIVE = "active"
LIFECYCLE_EXPERIMENTAL = "experimental"
LIFECYCLE_LEGACY = "legacy"
LIFECYCLE_DEPRECATED = "deprecated"

ALLOWED_LIFECYCLES = (
    LIFECYCLE_ACTIVE,
    LIFECYCLE_EXPERIMENTAL,
    LIFECYCLE_LEGACY,
    LIFECYCLE_DEPRECATED,
)


def is_allowed_lifecycle(lifecycle: str | None) -> bool:
    """Return True when a status value is allowed in the MVP."""

    return lifecycle in ALLOWED_LIFECYCLES


def count_lifecycles(blueprint_data: dict[str, Any]) -> dict[str, int]:
    """Count allowed status values declared in a blueprint payload."""
    from bpfw.catalog.schema import get_blocks, get_status

    counts = {status: 0 for status in ALLOWED_LIFECYCLES}
    blocks = get_blocks(blueprint_data)
    if not isinstance(blocks, list):
        return counts

    for block in blocks:
        if not isinstance(block, dict):
            continue
        status = get_status(block)
        if isinstance(status, str) and status in counts:
            counts[status] += 1

    return counts
