"""Wizard router integration for BPFW."""

from pathlib import Path
import sys

from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.inspect import run_inspect
from bpfw.integrations.plan import run_plan
from bpfw.integrations.result import OptionalIntegrationResult
from bpfw.integrations.wizard_router import (
    render_wizard_route_screen,
    select_wizard_route,
)


def can_use_interactive_terminal() -> bool:
    """Return True when standard streams support interactive routing."""

    return sys.stdin.isatty() and sys.stdout.isatty()


def run_wizard(project_root: Path) -> int:
    """Run the wizard router."""

    route = select_wizard_route(project_root=project_root)
    render_wizard_route_screen(route=route)

    if route.blocked:
        return route.exit_code

    if route.route_name == "inspect":
        if not can_use_interactive_terminal():
            print(
                "\nInteractive terminal unavailable.\n\n"
                "Detected route:\n"
                "  inspect\n\n"
                "Next:\n"
                "  Run this command in an interactive terminal:\n"
                "    bpfw inspect"
            )
            return 1
        return run_inspect(project_root=project_root)

    if route.route_name == "plan":
        if not can_use_interactive_terminal():
            print(
                "\nInteractive terminal unavailable.\n\n"
                "Detected route:\n"
                "  plan\n\n"
                "Next:\n"
                "  Run this command in an interactive terminal:\n"
                "    bpfw plan"
            )
            return 1
        return run_plan(project_root=project_root)

    return 0


class WizardRouterIntegration(OptionalIntegration):
    """Optional integration that routes users to inspect or plan."""

    name = "wizard"

    def is_available(self) -> bool:
        """Return True when the wizard router can run."""

        return True

    def run(self, project_root: Path) -> OptionalIntegrationResult:
        """Run wizard routing against the given project root."""

        exit_code = run_wizard(project_root=project_root)
        return OptionalIntegrationResult(message="", exit_code=exit_code)
