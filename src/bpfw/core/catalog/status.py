"""PURPOSE status rules for BPFW catalog mode
DOMAIN  blueprint checks
"""

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
    """PURPOSE check whether a status value is allowed in the
    DOMAIN  blueprint checks
    """

    return status in ALLOWED_STATUSES


def count_statuses(blueprint_data: dict[str, Any]) -> dict[str, int]:
    """PURPOSE count allowed status values declared in a blueprint data
        DOMAIN  blueprint checks

    """

    counts = {status: 0 for status in ALLOWED_STATUSES}
    blocks = blueprint_data.get("blocks", [])
    if not isinstance(blocks, list):
        return counts

    for block in blocks:
        if not isinstance(block, dict):
            continue
        status = block.get("status")
        if isinstance(status, str) and status in counts:
            counts[status] += 1

    return counts
