"""Inspector integration for BPFW catalog completion."""

import sys
from pathlib import Path

from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.inspector.session import run_text_inspector
from bpfw.integrations.result import OptionalIntegrationResult


def can_use_interactive_terminal() -> bool:
    """Return True when standard streams support interactive inspector input."""

    return sys.stdin.isatty() and sys.stdout.isatty()


def run_inspector(project_root: Path, show_all: bool = False) -> int:
    """Run the direct inspector integration."""

    if not can_use_interactive_terminal():
        print(
            "BPFW Inspector\n\n"
            "Interactive terminal unavailable.\n\n"
            "This command needs human authority input.\n\n"
            "Next:\n"
            "  Run this command in an interactive terminal:\n"
            "    bpfw inspector"
        )
        return 1

    return run_text_inspector(project_root=project_root, show_all=show_all)


class InspectorIntegration(OptionalIntegration):
    """Optional integration that completes authority data for existing code."""

    name = "inspector"

    def is_available(self) -> bool:
        """Return True when the inspector integration can run."""

        return True

    def run(
        self,
        project_root: Path,
        command_arguments: dict[str, str] | None = None,
    ) -> OptionalIntegrationResult:
        """Run inspector against the given project root."""

        arguments = command_arguments or {}
        show_all = arguments.get("view") == "all"
        exit_code = run_inspector(project_root=project_root, show_all=show_all)
        return OptionalIntegrationResult(message="", exit_code=exit_code)


__all__ = ["InspectorIntegration", "run_text_inspector"]
