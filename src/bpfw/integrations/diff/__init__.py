"""PURPOSE diff tool for BPFW drift decisions
DOMAIN  optional integrations
"""

import sys
from pathlib import Path

from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.diff.session import DiffSession
from bpfw.integrations.result import OptionalIntegrationResult


def can_use_interactive_terminal() -> bool:
    """PURPOSE check whether standard streams support interactive diff input
    DOMAIN  optional integrations
    """
    return sys.stdin.isatty() and sys.stdout.isatty()


def run_diff(project_root: Path) -> int:
    """PURPOSE run the interactive diff decision manager
    DOMAIN  optional integrations
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
    """PURPOSE optional tool that resolves blueprint-vs-code drift decisions
    DOMAIN  optional integrations
    """

    name = "diff"

    def is_available(self) -> bool:
        """PURPOSE check whether the diff tool can run
        DOMAIN  optional integrations
        """
        return True

    def run(
        self,
        project_root: Path,
        command_arguments: dict[str, str] | None = None,
    ) -> OptionalIntegrationResult:
        """PURPOSE run diff against the given project root
        DOMAIN  optional integrations
        """
        _ = command_arguments
        exit_code = run_diff(project_root=project_root)
        return OptionalIntegrationResult(message="", exit_code=exit_code)


__all__ = ["DiffIntegration", "run_diff"]
