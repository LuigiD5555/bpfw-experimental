"""Snapshot output for a validated blueprint."""

from __future__ import annotations

from dataclasses import dataclass

from bpfw.blueprint.models import BlueprintModel


@dataclass(slots=True)
class BlueprintSnapshot:
    """Small runtime snapshot used by verify command output."""

    blueprint_path: str
    responsibility_count: int



def build_snapshot(blueprint: BlueprintModel) -> BlueprintSnapshot:
    """Build deterministic snapshot from a validated model."""

    if blueprint.source_path is None:
        blueprint_path = ""
    else:
        blueprint_path = str(blueprint.source_path)
    return BlueprintSnapshot(
        blueprint_path=blueprint_path,
        responsibility_count=len(blueprint.responsibilities),
    )
