"""PURPOSE planner tool for blueprint-first planning and design
DOMAIN  planner workflow
"""

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
    """PURPOSE run the planner tool
    DOMAIN  planner workflow
    """

    controller = PlannerController(project_root=project_root)
    return controller.run()


class PlannerIntegration(OptionalIntegration):
    """PURPOSE optional tool for blueprint-first planning mode
    DOMAIN  planner workflow
    """

    name = "planner"

    def is_available(self) -> bool:
        """PURPOSE check whether the planner tool can run
        DOMAIN  planner workflow
        """

        return True

    def run(
        self,
        project_root: Path,
        command_arguments: dict[str, str] | None = None,
    ) -> OptionalIntegrationResult:
        """PURPOSE run planner against the given project root
        DOMAIN  planner workflow
        """

        _ = command_arguments
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
