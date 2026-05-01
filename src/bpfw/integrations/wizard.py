"""Wizard integration for BPFW MVP catalog completion."""

from pathlib import Path
import sys

from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.result import OptionalIntegrationResult
from bpfw.integrations.wizard_base import (
    apply_automatic_authority_fields,
    complete_human_fields,
    get_incomplete_responsibilities,
    suggest_owner_layer,
)
from bpfw.integrations.wizard_text import run_text_wizard


def _can_use_interactive_terminal() -> bool:
    """Return True when standard streams can support an interactive wizard."""

    return sys.stdin.isatty() and sys.stdout.isatty()


def _run_automatic_fallback(project_root: Path) -> int:
    print("Interactive wizard unavailable. Running automatic fallback.")
    blueprint_path, updated_entries = complete_human_fields(project_root=project_root)
    print(f"Wizard completed. Updated fields: {updated_entries}")
    print(f"Blueprint saved at: {blueprint_path}")
    return 0


def run_wizard(project_root: Path) -> int:
    """Run the free text wizard integration."""

    if not _can_use_interactive_terminal():
        return _run_automatic_fallback(project_root=project_root)
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
