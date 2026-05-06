"""Planner integration placeholder for blueprint-first planning."""

from pathlib import Path

from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.result import OptionalIntegrationResult


def run_planner(project_root: Path) -> int:
    """Run the planner integration placeholder."""

    _ = project_root
    print(
        "BPFW Planner\n\n"
        "Planner mode is not implemented yet.\n\n"
        "Purpose:\n"
        "  Define planned responsibilities before code exists.\n"
        "  Future versions may use this data for scaffolding.\n\n"
        "Current focus:\n"
        "  Use bpfw inspector for existing code."
    )
    return 0


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