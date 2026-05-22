"""Blueprint Engine for approved mechanical mutations under ``bpfw/``.

The engine applies explicit authority changes such as creating blocks, moving blocks, updating code references, and
editing shard files. It never detects drift and never silently synchronizes the
blueprint from code.
"""

from bpfw.core.blueprint_engine.engine import BlueprintEngine
from bpfw.core.blueprint_engine.models import (
    BlueprintChangeKind,
    BlueprintChangePreview,
    BlueprintChangeRequest,
    BlueprintChangeResult,
    BlueprintChangeSource,
    MechanicalChangeEvidence,
)
from bpfw.core.blueprint_engine.planner import BlueprintPlanBuilder
from bpfw.core.blueprint_engine.safety import BlueprintEngineSafetyPolicy

__all__ = [
    "BlueprintEngine",
    "BlueprintChangeKind",
    "BlueprintChangePreview",
    "BlueprintChangeRequest",
    "BlueprintChangeResult",
    "BlueprintChangeSource",
    "MechanicalChangeEvidence",
    "BlueprintPlanBuilder",
    "BlueprintEngineSafetyPolicy",
]
