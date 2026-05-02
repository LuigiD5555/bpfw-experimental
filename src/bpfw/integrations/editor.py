"""Editor integration placeholder for authority-first blueprint workflows."""

from pathlib import Path

from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.result import OptionalIntegrationResult


def run_editor(project_root: Path) -> int:
    """Run the editor integration placeholder."""

    print(
        "BPFW Editor\n\n"
        "Editor mode is not implemented yet.\n\n"
        "Purpose:\n"
        "  Navigate, correct, or reorganize the existing blueprint authority.\n\n"
        "Next:\n"
        "  Use bpfw status to review blueprint state."
    )
    return 1


class EditorIntegration(OptionalIntegration):
    """Optional integration for authority-first blueprint editing mode."""

    name = "editor"

    def is_available(self) -> bool:
        """Return True when the editor integration can run."""

        return True

    def run(self, project_root: Path) -> OptionalIntegrationResult:
        """Run editor against the given project root."""

        exit_code = run_editor(project_root=project_root)
        return OptionalIntegrationResult(message="", exit_code=exit_code)
