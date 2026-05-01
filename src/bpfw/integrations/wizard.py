"""Wizard integration for BPFW MVP catalog completion."""

from pathlib import Path
from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.result import OptionalIntegrationResult
from bpfw.integrations.wizard_base import (
    apply_automatic_authority_fields,
    complete_human_fields,
    get_incomplete_responsibilities,
    suggest_owner_layer,
)
from bpfw.integrations.wizard_text import run_text_wizard


def run_wizard(project_root: Path) -> int:
    """Run the free text wizard integration."""

    return run_text_wizard(project_root=project_root)


class RichWizardIntegration(OptionalIntegration):
    """Optional wizard integration for catalog completion."""

    name = "wizard"

    def is_available(self) -> bool:
        """Return True when the wizard integration can run."""

        return True

    def run(self, project_root: Path) -> OptionalIntegrationResult:
        """Run the wizard integration."""

        exit_code = run_wizard(project_root=project_root)
        return OptionalIntegrationResult(message="", exit_code=exit_code)
