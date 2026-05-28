"""PURPOSE editor tool for search-first block editing
DOMAIN  editor workflow
"""

import sys
from pathlib import Path

from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.result import OptionalIntegrationResult


def can_use_interactive_terminal() -> bool:
    """PURPOSE check whether standard streams support interactive editor input
    DOMAIN  editor workflow
    """

    return sys.stdin.isatty() and sys.stdout.isatty()


def run_interactive_editor(project_root: Path) -> int:
    """PURPOSE run the interactive terminal editor session
    DOMAIN  editor workflow
    """

    from bpfw.integrations.editor.session import EditorSession

    session = EditorSession(project_root=project_root)
    return session.run()


def run_editor(project_root: Path) -> int:
    """PURPOSE run the editor tool
    DOMAIN  editor workflow
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
    """PURPOSE optional tool for search-first blueprint block editing
    DOMAIN  editor workflow
    """

    name = "editor"

    def is_available(self) -> bool:
        """PURPOSE check whether the editor tool can run
        DOMAIN  editor workflow
        """

        return True

    def run(
        self,
        project_root: Path,
        command_arguments: dict[str, str] | None = None,
    ) -> OptionalIntegrationResult:
        """PURPOSE run editor against the given project root
        DOMAIN  editor workflow
        """

        _ = command_arguments
        exit_code = run_editor(project_root=project_root)
        return OptionalIntegrationResult(message="", exit_code=exit_code)


__all__ = ["EditorIntegration", "run_editor", "run_interactive_editor"]
