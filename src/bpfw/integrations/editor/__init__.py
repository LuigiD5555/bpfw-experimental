"""BPFW Editor — search-first responsibility launcher.

The editor searches blueprint responsibilities and delegates editing to Inspector.
"""

import sys
from pathlib import Path

from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.result import OptionalIntegrationResult


def run_interactive_editor(project_root: Path) -> int:
    """Run the interactive terminal editor session.

    Returns exit code: 0 for normal exit, 1 for errors.
    """

    from bpfw.integrations.editor.session import EditorSession

    session = EditorSession(project_root=project_root)

    return session.run()


def run_editor(project_root: Path) -> int:
    """Entry point for the editor integration."""

    if not sys.stdin.isatty() or not sys.stdout.isatty():
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
    """Optional integration for authority-first blueprint editing."""

    name = "editor"

    def is_available(self) -> bool:
        """Return True when the editor integration can run."""

        return True

    def run(self, project_root: Path) -> OptionalIntegrationResult:
        """Run editor against the given project root."""

        exit_code = run_editor(project_root=project_root)
        return OptionalIntegrationResult(message="", exit_code=exit_code)
