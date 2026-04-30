"""Lifecycle rules for BPFW MVP Catalog Mode."""

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
    """Return True when a lifecycle value is allowed in the MVP."""

    return lifecycle in ALLOWED_LIFECYCLES


def count_lifecycles(blueprint_data: dict[str, Any]) -> dict[str, int]:
    """Count allowed lifecycle values declared in a blueprint payload."""

    counts = {lifecycle: 0 for lifecycle in ALLOWED_LIFECYCLES}
    responsibilities = blueprint_data.get("responsibilities")
    if not isinstance(responsibilities, list):
        return counts

    for responsibility in responsibilities:
        if not isinstance(responsibility, dict):
            continue
        lifecycle = responsibility.get("lifecycle")
        if isinstance(lifecycle, str) and lifecycle in counts:
            counts[lifecycle] += 1

    return counts
