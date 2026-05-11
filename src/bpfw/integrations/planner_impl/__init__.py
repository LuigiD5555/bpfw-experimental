"""Planner integration for blueprint-first system design."""

from bpfw.integrations.planner_impl.connection_detection import InferredConnection, detect_connections
from bpfw.integrations.planner_impl.connection_merge import merge_connections
from bpfw.integrations.planner_impl.models import (
    PlannerBox,
    PlannerConnection,
    PlannerInterface,
    PlannerInterfaceInput,
    PlannerInterfaceOutput,
    PlannerProjectConfig,
    PlannerSecurityConfig,
    PlannerState,
)

__all__ = [
    "PlannerBox",
    "PlannerConnection",
    "PlannerInterface",
    "PlannerInterfaceInput",
    "PlannerInterfaceOutput",
    "PlannerProjectConfig",
    "PlannerSecurityConfig",
    "PlannerState",
    "InferredConnection",
    "detect_connections",
    "merge_connections",
]

# Note: run_planner and PlannerIntegration are available from the parent module
# They are defined in src/bpfw/integrations/planner.py
