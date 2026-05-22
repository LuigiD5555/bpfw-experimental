"""Reusable protection setup and repair orchestration."""

from dataclasses import dataclass
from pathlib import Path

from bpfw.core.catalog.paths import CANONICAL_BLUEPRINT_FILE
from bpfw.core.protection.authority import lock_authority
from bpfw.core.protection.capabilities import LockSupportResult, check_lock_support

UNPROTECTED_STATUS = "unprotected"


@dataclass(frozen=True, slots=True)
class ProtectionSetupResult:
    """Combined result for local BPFW OS protection setup."""

    blueprint_exists: bool
    lock_state: str
    support: LockSupportResult | None = None
    allow_unprotected: bool = False

    @property
    def allowed(self) -> bool:
        """Return whether init may succeed with the current protection state."""

        return self.blueprint_exists and (
            self.lock_state == "locked"
            or self.lock_state == "degraded"
            or (self.allow_unprotected and self.lock_state == UNPROTECTED_STATUS)
        )


def _protection_line(lock_state: str) -> str:
    """Return the user-facing protection line for a lock state."""

    if lock_state == "locked":
        return "enabled"
    if lock_state == UNPROTECTED_STATUS:
        return "disabled by --allow-unprotected"
    if lock_state == "unsupported":
        return "unsupported"
    if lock_state == "degraded":
        return "partially enabled"
    if lock_state == "unknown":
        return "unknown"
    return lock_state


def _action_for_result(result: ProtectionSetupResult) -> str:
    """Return the init summary action that matches the actual protection result."""

    if result.lock_state == "locked":
        return "protection configured"
    if result.lock_state == UNPROTECTED_STATUS:
        return "protection disabled"
    if result.lock_state == "degraded":
        return "protection partially configured"
    return "protection failed"


def _reason_lines(result: ProtectionSetupResult) -> list[str]:
    """Build reason lines for non-locked protection setup results."""

    if result.lock_state == UNPROTECTED_STATUS:
        return [
            "Reason:",
            "  OS protection was explicitly skipped with --allow-unprotected.",
            "",
            "Next:",
            "  Run bpfw lock from a supported filesystem before relying on authority protection.",
        ]

    reason = "BPFW could not enforce OS protection for authority resources."
    checked_path = None
    if result.support is not None:
        reason = result.support.reason
        checked_path = result.support.checked_path

    lines = [
        "Reason:",
        f"  {reason}",
    ]
    if checked_path is not None:
        lines.extend(
            [
                "",
                "Checked path:",
                f"  {checked_path}",
            ]
        )
    if result.support is not None and (
        "read-only permission protection did not block normal writes" in result.support.reason
    ):
        lines.extend(
            [
                "",
                "Next:",
                "  Move the project to a filesystem that enforces POSIX ownership or permissions,",
                "  remount this filesystem with real permission support,",
                "  or rerun init with --allow-unprotected for explicit unprotected development.",
            ]
        )
        return lines

    lines.extend(
        [
            "",
            "Next:",
            "  Run this command from an interactive terminal where sudo can prompt,",
            "  use a filesystem that preserves POSIX ownership or permission changes,",
            "  or rerun init with --allow-unprotected for explicit unprotected development.",
        ]
    )
    return lines


def format_setup_summary(result: ProtectionSetupResult, action: str | None = None) -> str:
    """Format protection setup details with state-aware wording."""

    resolved_action = action if action is not None else _action_for_result(result=result)
    lines = [
        f"BPFW {resolved_action}.",
        "",
        "Blueprint:",
        f"  path: {CANONICAL_BLUEPRINT_FILE}",
        f"  exists: {str(result.blueprint_exists).lower()}",
        "",
        "Authority protection:",
        f"  os lock: {_protection_line(lock_state=result.lock_state)}",
        "  scope: blueprint and BPFW guard files",
    ]

    if result.support is not None:
        lines.append(f"  backend: {result.support.backend}")

    if result.lock_state != "locked":
        lines.extend(["", *_reason_lines(result=result)])

    return "\n".join(lines)


def run_protection_setup(project_root: Path, allow_unprotected: bool = False) -> ProtectionSetupResult:
    """Lock the full BPFW authority surface at OS level after a capability preflight."""

    blueprint_path = project_root / CANONICAL_BLUEPRINT_FILE
    support = check_lock_support(project_root=project_root)
    if not support.supported:
        lock_state = UNPROTECTED_STATUS if allow_unprotected else support.status
        return ProtectionSetupResult(
            blueprint_exists=blueprint_path.exists(),
            lock_state=lock_state,
            support=support,
            allow_unprotected=allow_unprotected,
        )

    lock_state = lock_authority(project_root=project_root).status
    return ProtectionSetupResult(
        blueprint_exists=blueprint_path.exists(),
        lock_state=lock_state,
        support=support,
        allow_unprotected=allow_unprotected,
    )


