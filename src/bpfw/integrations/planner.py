"""Planner integration for blueprint-first planning."""

from pathlib import Path

from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.planner_impl.controller import PlannerController
from bpfw.integrations.result import OptionalIntegrationResult


def run_planner(project_root: Path) -> int:
    """Run the planner integration.
    
    Args:
        project_root: Root directory of the project.
    
    Returns:
        Exit code (0 for success, 1 for error).
    """
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