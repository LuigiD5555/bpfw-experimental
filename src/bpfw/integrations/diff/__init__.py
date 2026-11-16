"""Diff integration for BPFW drift decisions."""

import sys
from pathlib import Path

from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.diff.session import DiffSession
from bpfw.integrations.result import OptionalIntegrationResult


def can_use_interactive_terminal() -> bool:
    """Return True when standard streams support interactive diff input.

    Returns:
        True when stdin and stdout are attached to a terminal.
    """
    return sys.stdin.isatty() and sys.stdout.isatty()


def run_diff(project_root: Path) -> int:
    """Run the interactive diff decision manager.

    Args:
        project_root: Root directory of the project being reviewed.

    Returns:
        Process exit code.
    """
    if not can_use_interactive_terminal():
        print(
            "BPFW Diff Manager\n\n"
            "Interactive terminal unavailable.\n\n"
            "This command needs human authority decisions.\n\n"
            "Next:\n"
            "  Run this command in an interactive terminal:\n"
            "    bpfw diff"
        )
        return 1

    session = DiffSession(project_root=project_root)
    return session.run()


class DiffIntegration(OptionalIntegration):
    """Optional integration that resolves blueprint-vs-code drift decisions."""

    name = "diff"

    def is_available(self) -> bool:
        """Return True when the diff integration can run.

        Returns:
            Always True for the bundled terminal diff manager.
        """
        return True

    def run(
        self,
        project_root: Path,
        command_arguments: dict[str, str] | None = None,
    ) -> OptionalIntegrationResult:
        """Run diff against the given project root."""
        _ = command_arguments
        exit_code = run_diff(project_root=project_root)
        return OptionalIntegrationResult(message="", exit_code=exit_code)


__all__ = ["DiffIntegration", "run_diff"]
