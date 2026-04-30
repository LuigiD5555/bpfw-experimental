"""Resolver helpers for relationship checks in blueprint models."""

from __future__ import annotations

from bpfw.blueprint.models import BlueprintResponsibility



def build_implementation_index(responsibility: BlueprintResponsibility) -> dict[str, str]:
    """Return implementation_id -> lifecycle_state for one responsibility."""

    return {
        implementation.implementation_id: implementation.lifecycle_state
        for implementation in responsibility.allowed_implementations
    }
