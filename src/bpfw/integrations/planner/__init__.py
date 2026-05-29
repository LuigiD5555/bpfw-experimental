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


class PlannerIntegration(OptionalIntegration):
    """Optional integration for blueprint-first planning mode."""

    name = "planner"

    def is_available(self) -> bool:
        """Return True when the planner integration can run."""

        return True

    def run(
        self,
        project_root: Path,
        command_arguments: dict[str, str] | None = None,
    ) -> OptionalIntegrationResult:
        """Run planner against the given project root."""

        _ = command_arguments
        controller = PlannerController(project_root=project_root)
        exit_code = controller.run()
        return OptionalIntegrationResult(message="", exit_code=exit_code)


__all__ = [
    "PlannerIntegration",
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
