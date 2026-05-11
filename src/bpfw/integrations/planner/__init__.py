"""Planner integration for blueprint-first planning and design."""

from pathlib import Path

from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.planner.connection_detection import InferredConnection, detect_connections
from bpfw.integrations.planner.connection_merge import merge_connections
from bpfw.integrations.planner.controller import PlannerController
from bpfw.integrations.planner.models import (
    PlannerBox,
    PlannerConnection,
    PlannerInterface,
    PlannerInterfaceInput,
    PlannerInterfaceOutput,
    PlannerProjectConfig,
    PlannerSecurityConfig,
    PlannerState,
)
from bpfw.integrations.result import OptionalIntegrationResult


def run_planner(project_root: Path) -> int:
    """Run the planner integration."""

    controller = PlannerController(project_root=project_root)
    return controller.run()


class PlannerIntegration(OptionalIntegration):
    """Optional integration for blueprint-first planning mode."""

    name = "planner"

    def is_available(self) -> bool:
        """Return True when the planner integration can run."""

        return True

    def run(self, project_root: Path) -> OptionalIntegrationResult:
        """Run planner against the given project root."""

        exit_code = run_planner(project_root=project_root)
        return OptionalIntegrationResult(message="", exit_code=exit_code)


__all__ = [
    "PlannerIntegration",
    "run_planner",
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
