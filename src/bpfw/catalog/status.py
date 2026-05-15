"""Status rules for BPFW MVP Catalog Mode."""

from typing import Any

STATUS_ACTIVE = "active"
STATUS_EXPERIMENTAL = "experimental"
STATUS_LEGACY = "legacy"
STATUS_DEPRECATED = "deprecated"

ALLOWED_STATUSES = (
    STATUS_ACTIVE,
    STATUS_EXPERIMENTAL,
    STATUS_LEGACY,
    STATUS_DEPRECATED,
)


def is_allowed_status(status: str | None) -> bool:
    """Return True when a status value is allowed in the MVP."""

    return status in ALLOWED_STATUSES


def count_statuses(blueprint_data: dict[str, Any]) -> dict[str, int]:
    """Count allowed status values declared in a blueprint payload."""

    from bpfw.catalog.schema import get_blocks, get_status

    counts = {status: 0 for status in ALLOWED_STATUSES}
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
