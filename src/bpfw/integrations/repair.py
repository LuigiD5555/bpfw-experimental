"""Protection repair integration for BPFW MVP Catalog Mode."""

from pathlib import Path

from bpfw.catalog.paths import CANONICAL_BLUEPRINT_FILE
from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.result import OptionalIntegrationResult
from bpfw.protection import setup as protection_setup


def run_repair(project_root: Path) -> tuple[bool, str, int]:
    """Repair an existing BPFW project without regenerating the blueprint."""

    blueprint_path = project_root / CANONICAL_BLUEPRINT_FILE
    if not blueprint_path.exists():
        message = (
            "BPFW repair blocked.\n\n"
            "Blueprint:\n"
            f"  missing: {CANONICAL_BLUEPRINT_FILE}\n\n"
            "Next:\n"
            "  Run bpfw init."
        )
        return False, message, 1

    result = protection_setup.run_protection_setup(project_root=project_root)
    message = protection_setup.format_setup_summary(
        result=result,
        action="repair completed",
    )
    return result.allowed, message, 0 if result.allowed else 1


class ProtectionRepairIntegration(OptionalIntegration):
    """Optional local authority repair integration."""

    name = "repair"

    def is_available(self) -> bool:
        """Return True when the built-in repair integration can run."""

        return True

    def run(self, project_root: Path) -> OptionalIntegrationResult:
        """Run local protection repair."""

        _success, message, exit_code = run_repair(project_root=project_root)
        return OptionalIntegrationResult(message=message, exit_code=exit_code)
