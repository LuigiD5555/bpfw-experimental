"""Plan integration placeholder for blueprint-first workflows."""

from pathlib import Path

from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.result import OptionalIntegrationResult


def run_plan(project_root: Path) -> int:
    """Run the plan integration placeholder."""

    print(
        "BPFW Plan\n\n"
        "Plan mode is not implemented yet.\n\n"
        "Purpose:\n"
        "  Define planned responsibilities before code exists.\n\n"
        "Next:\n"
        "  Use bpfw inspect for existing code."
    )
    return 1


class PlanIntegration(OptionalIntegration):
    """Optional integration for blueprint-first planning mode."""

    name = "plan"

    def is_available(self) -> bool:
        """Return True when the plan integration can run."""

        return True

    def run(self, project_root: Path) -> OptionalIntegrationResult:
        """Run plan against the given project root."""

        exit_code = run_plan(project_root=project_root)
        return OptionalIntegrationResult(message="", exit_code=exit_code)
