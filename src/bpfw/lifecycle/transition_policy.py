"""Lifecycle policy helpers for active implementation constraints."""

from __future__ import annotations

from dataclasses import dataclass

from bpfw.lifecycle.states import LifecycleState


@dataclass(slots=True)
class TransitionDecision:
    """Policy decision for whether implementation can be active by default."""

    allowed: bool
    code: str | None = None
    message: str | None = None
    recommendation: str | None = None



def can_be_active_by_default(state: str, explicit_approval: bool = False) -> TransitionDecision:
    """Evaluate whether a lifecycle state can be wired as active_implementation."""

    if state == LifecycleState.ACTIVE.value:
        return TransitionDecision(allowed=True)
    if state == LifecycleState.PLANNED.value:
        return TransitionDecision(
            allowed=False,
            code="LC004",
            message="planned implementation cannot be active_implementation",
            recommendation="Promote implementation to active only when ready for execution",
        )
    if state == LifecycleState.EXPERIMENTAL.value:
        if explicit_approval:
            return TransitionDecision(allowed=True)
        return TransitionDecision(
            allowed=False,
            code="LC005",
            message="experimental implementation cannot be active_implementation without approval",
            recommendation="Keep active_implementation on stable active implementation",
        )
    if state == LifecycleState.DISABLED.value:
        return TransitionDecision(
            allowed=False,
            code="LC006",
            message="disabled implementation cannot be active_implementation",
            recommendation="Select a non-disabled implementation as active_implementation",
        )
    if state == LifecycleState.LEGACY.value:
        return TransitionDecision(
            allowed=False,
            code="LC009",
            message="legacy implementation cannot be active_implementation",
            recommendation="Migrate active_implementation to supported active implementation",
        )
    return TransitionDecision(allowed=True)
