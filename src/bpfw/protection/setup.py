"""Reusable protection setup and repair orchestration."""

from dataclasses import dataclass
from pathlib import Path

from bpfw.catalog.paths import CANONICAL_BLUEPRINT_FILE
from bpfw.protection.authority import lock_authority


@dataclass(frozen=True, slots=True)
class ProtectionSetupResult:
    """Combined result for local BPFW OS protection setup."""

    blueprint_exists: bool
    lock_state: str

    @property
    def allowed(self) -> bool:
        return self.blueprint_exists and self.lock_state == "locked"


def _format_setup_summary(result: ProtectionSetupResult, action: str) -> str:
    protection_line = (
        "enabled"
        if result.lock_state == "locked"
        else f"blocked ({result.lock_state})"
    )

    lines = [
        f"BPFW {action}.",
        "",
        "Blueprint:",
        f"  path: {CANONICAL_BLUEPRINT_FILE}",
        f"  exists: {str(result.blueprint_exists).lower()}",
        "",
        "Authority protection:",
        f"  os lock: {protection_line}",
        "  scope: blueprint and BPFW guard files",
    ]

    if result.lock_state != "locked":
        lines.extend(
            [
                "",
                "Reason:",
                "  BPFW could not enforce OS protection for authority resources.",
                "",
                "Next:",
                "  Run this command from an interactive terminal where sudo can prompt,",
                "  or move the project to a filesystem that supports ownership changes",
                "  or immutable flags.",
            ]
        )

    return "\n".join(lines)


def run_protection_setup(project_root: Path) -> ProtectionSetupResult:
    """Lock the full BPFW authority surface at OS level."""

    blueprint_path = project_root / CANONICAL_BLUEPRINT_FILE
    lock_state = lock_authority(project_root=project_root).status
    return ProtectionSetupResult(
        blueprint_exists=blueprint_path.exists(),
        lock_state=lock_state,
    )


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

    result = run_protection_setup(project_root=project_root)
    message = _format_setup_summary(result=result, action="repair completed")
    return result.allowed, message, 0 if result.allowed else 1


def format_init_setup_summary(result: ProtectionSetupResult) -> str:
    """Format protection setup details for init output."""

    return _format_setup_summary(result=result, action="protection configured")
