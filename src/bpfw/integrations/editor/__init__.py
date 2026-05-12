"""Editor integration for search-first block editing."""

import sys
from pathlib import Path

from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.result import OptionalIntegrationResult


def can_use_interactive_terminal() -> bool:
    """Return True when standard streams support interactive editor input."""

    return sys.stdin.isatty() and sys.stdout.isatty()


def run_interactive_editor(project_root: Path) -> int:
    """Run the interactive terminal editor session.

    Args:
        project_root: Root directory of the project being edited.

    Returns:
        Process exit code produced by the editor session.
    """

    from bpfw.integrations.editor.session import EditorSession

    session = EditorSession(project_root=project_root)
    return session.run()


def run_editor(project_root: Path) -> int:
    """Run the editor integration.

    Args:
        project_root: Root directory of the project being edited.

    Returns:
        Process exit code for the command.
    """

    if not can_use_interactive_terminal():
        print(
            "BPFW Editor\n\n"
            "Interactive terminal unavailable.\n\n"
            "This command needs an interactive terminal.\n\n"
            "Next:\n"
            "  Run this command in an interactive terminal:\n"
            "    bpfw editor"
        )
        return 1

    return run_interactive_editor(project_root=project_root)


class EditorIntegration(OptionalIntegration):
    """Optional integration for search-first blueprint block editing."""

    name = "editor"

    def is_available(self) -> bool:
        """Return True when the editor integration can run."""

        return True

    def run(self, project_root: Path) -> OptionalIntegrationResult:
        """Run editor against the given project root.

        Args:
            project_root: Root directory of the project being edited.

        Returns:
            Integration result containing the editor exit code.
        """

        exit_code = run_editor(project_root=project_root)
        return OptionalIntegrationResult(message="", exit_code=exit_code)


__all__ = ["EditorIntegration", "run_editor", "run_interactive_editor"]
