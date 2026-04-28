"""Policy helpers for blueprint_mode execution gating."""

from __future__ import annotations

from bpfw.blueprint_mode.models import BlueprintModeConfig



def should_validate_blueprint_mode(config: BlueprintModeConfig) -> bool:
    """Return whether blueprint_mode contracts must be validated."""

    return bool(config.enabled)
