"""Official lifecycle states for Blueprint Framework."""

from __future__ import annotations

from enum import StrEnum


class LifecycleState(StrEnum):
    """Supported lifecycle states for responsibilities and implementations."""

    PLANNED = "planned"
    ACTIVE = "active"
    EXPERIMENTAL = "experimental"
    DISABLED = "disabled"
    DEPRECATED = "deprecated"
    LEGACY = "legacy"


OFFICIAL_STATES: set[str] = {state.value for state in LifecycleState}
