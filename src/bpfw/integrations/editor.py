"""Editor integration placeholder for authority-first blueprint editing."""

from pathlib import Path

from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.result import OptionalIntegrationResult


def run_editor(project_root: Path) -> int:
    """Run the editor integration placeholder."""

    _ = project_root
    print(
        "BPFW Editor\n\n"
        "Editor mode is not implemented yet.\n\n"
        "Purpose:\n"
        "  Search and edit existing blueprint responsibilities.\n\n"
        "Future capabilities:\n"
        "  Search by intent, name, lifecycle, domain, path, symbol, or id.\n"
        "  Filter responsibilities by lifecycle or domain."
    )
    return 0


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