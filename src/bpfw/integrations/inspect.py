"""Inspect integration for BPFW catalog authority completion."""

from pathlib import Path
import sys

from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.inspect_text import run_text_inspect
from bpfw.integrations.result import OptionalIntegrationResult


def can_use_interactive_terminal() -> bool:
    """Return True when standard streams support interactive inspect."""

    return sys.stdin.isatty() and sys.stdout.isatty()


def run_inspect(project_root: Path) -> int:
    """Run the inspect integration."""

    if not can_use_interactive_terminal():
        print(
            "BPFW Inspect\n\n"
            "Interactive terminal unavailable.\n\n"
            "This command needs human authority input.\n\n"
            "Next:\n"
            "  Run this command in an interactive terminal:\n"
            "    bpfw inspect"
        )
        return 1

    return run_text_inspect(project_root=project_root)


class InspectIntegration(OptionalIntegration):
    """Optional integration that completes authority data for existing code."""

    name = "inspect"

    def is_available(self) -> bool:
        """Return True when the inspect integration can run."""

        return True

    def run(self, project_root: Path) -> OptionalIntegrationResult:
        """Run inspect against the given project root."""

        exit_code = run_inspect(project_root=project_root)
        return OptionalIntegrationResult(message="", exit_code=exit_code)
