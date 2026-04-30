"""Command registry for BPFW MVP Catalog Mode."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bpfw.catalog.paths import CANONICAL_BLUEPRINT_FILE
from bpfw.catalog.verify import run_verify
from bpfw.catalog.wizard import complete_human_fields
from bpfw.catalog.writer import run_init
from bpfw.core.pipeline import Pipeline, PipelineStep
from bpfw.core.result import ResultStatus, StepResult
from bpfw.protection.state import UnlockWindow, load_authority_state, save_authority_state


def _parse_ttl_to_minutes(raw_ttl: str) -> int:
    """Parse a TTL string into minutes."""

    normalized_ttl = raw_ttl.strip().lower()
    if not normalized_ttl:
        raise ValueError("Missing --ttl value")
    if normalized_ttl.endswith("m"):
        return int(normalized_ttl[:-1] or "0")
    if normalized_ttl.endswith("h"):
        return int(normalized_ttl[:-1] or "0") * 60
    return int(normalized_ttl)


def _is_unlock_window_active(unlock_window: UnlockWindow | None) -> bool:
    """Return True when the current blueprint unlock window is still valid."""

    if unlock_window is None or unlock_window.resource_id != "project_blueprint":
        return False

    try:
        expiration_time = datetime.fromisoformat(unlock_window.expires_at)
    except ValueError:
        return False

    if expiration_time.tzinfo is None:
        expiration_time = expiration_time.replace(tzinfo=timezone.utc)

    return expiration_time > datetime.now(timezone.utc)


def _is_blueprint_locked(project_root: Path) -> bool:
    """Return lock state for the MVP blueprint resource."""

    state = load_authority_state(project_root=project_root)
    return not _is_unlock_window_active(state.active_unlock_window)


@dataclass(slots=True)
class InitProjectStep(PipelineStep):
    """Initialize the catalog blueprint file."""

    name: str = "catalog.init"

    def run(self, context) -> StepResult:  # noqa: ANN001
        _success, message, exit_code = run_init(project_root=context.project_root)
        return StepResult(
            status=ResultStatus.OK if exit_code == 0 else ResultStatus.BLOCK,
            message=message,
            source=self.name,
            details={"blueprint_path": CANONICAL_BLUEPRINT_FILE},
        )


@dataclass(slots=True)
class WizardStep(PipelineStep):
    """Complete human catalog fields deterministically."""

    name: str = "catalog.wizard"

    def run(self, context) -> StepResult:  # noqa: ANN001
        if _is_blueprint_locked(project_root=context.project_root):
            return StepResult(
                status=ResultStatus.BLOCK,
                message="BLOCK: Blueprint is locked. Run bpfw unlock before editing.",
                source=self.name,
                details={"error_code": "WIZARD_LOCKED"},
            )

        blueprint_path, updated_entries = complete_human_fields(project_root=context.project_root)
        return StepResult(
            status=ResultStatus.OK,
            message=f"Wizard completed. Updated fields: {updated_entries}",
            source=self.name,
            details={"blueprint_path": str(blueprint_path), "updated_fields": str(updated_entries)},
            affected_resources=[str(blueprint_path)],
        )


@dataclass(slots=True)
class VerifyBlueprintStep(PipelineStep):
    """Run the canonical catalog verify pipeline."""

    name: str = "catalog.verify"

    def run(self, context) -> StepResult:  # noqa: ANN001
        report, exit_code = run_verify(project_root=context.project_root)
        block_findings = [finding for finding in report.findings if finding.severity == "block"]
        details = {
            "authority_state": report.authority_state,
            "declared_count": str(report.declared_count),
            "discovered_count": str(report.discovered_count),
            "missing_declared_code": str(report.missing_declared_count),
            "undeclared_code": str(report.undeclared_count),
            "duplicate_active_intents": str(report.duplicate_active_intent_count),
            "invalid_lifecycles": str(report.invalid_lifecycle_count),
            "incomplete_responsibilities": str(report.incomplete_responsibility_count),
        }

        if exit_code != 0:
            first_finding = block_findings[0] if block_findings else None
            return StepResult(
                status=ResultStatus.BLOCK,
                message=first_finding.message if first_finding else "BPFW VERIFY BLOCKED",
                source=self.name,
                details=details,
                affected_resources=[first_finding.path or CANONICAL_BLUEPRINT_FILE] if first_finding else [],
                suggested_actions=["Update bpfw/blueprint.yaml, then run bpfw verify"],
            )

        return StepResult(
            status=ResultStatus.OK,
            message="BPFW VERIFY PASSED",
            source=self.name,
            details=details,
        )


@dataclass(slots=True)
class AuthorityLockStep(PipelineStep):
    """Lock the MVP blueprint resource."""

    name: str = "protection.lock"

    def run(self, context) -> StepResult:  # noqa: ANN001
        state = load_authority_state(project_root=context.project_root)
        state.active_unlock_window = None
        state.last_relock_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        save_authority_state(project_root=context.project_root, state=state)

        return StepResult(
            status=ResultStatus.OK,
            message=f"Blueprint locked: {CANONICAL_BLUEPRINT_FILE}",
            source=self.name,
            details={"lock_state": "locked", "resource_id": "project_blueprint"},
        )


@dataclass(slots=True)
class AuthorityUnlockStep(PipelineStep):
    """Open a scoped unlock window for the MVP blueprint resource."""

    name: str = "protection.unlock"

    def run(self, context) -> StepResult:  # noqa: ANN001
        ttl_minutes = _parse_ttl_to_minutes(context.command_arguments.get("ttl", "10m"))
        if ttl_minutes <= 0:
            return StepResult(
                status=ResultStatus.BLOCK,
                message="ttl must be greater than zero",
                source=self.name,
                details={"error_code": "AUTH_UNLOCK_TTL"},
            )

        expiration_time = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        unlock_window = UnlockWindow(
            resource_id="project_blueprint",
            resource_path=CANONICAL_BLUEPRINT_FILE,
            scope=str(context.command_arguments.get("scope", "manual") or "manual"),
            operation=str(context.command_arguments.get("operation", "unlock") or "unlock"),
            expires_at=expiration_time.replace(microsecond=0).isoformat(),
        )

        state = load_authority_state(project_root=context.project_root)
        state.active_unlock_window = unlock_window
        save_authority_state(project_root=context.project_root, state=state)

        return StepResult(
            status=ResultStatus.OK,
            message=f"Blueprint unlocked for {ttl_minutes} minutes",
            source=self.name,
            details={"resource_id": "project_blueprint", "expires_at": unlock_window.expires_at},
        )


@dataclass(slots=True)
class AuthorityStatusStep(PipelineStep):
    """Report compact MVP status for engine callers."""

    name: str = "catalog.status"

    def run(self, context) -> StepResult:  # noqa: ANN001
        report, _exit_code = run_verify(project_root=context.project_root)
        lock_state = "locked" if _is_blueprint_locked(project_root=context.project_root) else "unlocked"
        drift_state = "drift" if report.missing_declared_count or report.undeclared_count else "clean"
        lifecycle_state = "invalid" if report.invalid_lifecycle_count else "valid"

        return StepResult(
            status=ResultStatus.OK if report.allowed else ResultStatus.BLOCK,
            message="MVP status reported",
            source=self.name,
            details={
                "lock": lock_state,
                "blueprint_state": report.authority_state,
                "drift_state": drift_state,
                "lifecycle_state": lifecycle_state,
                "declared_count": str(report.declared_count),
                "discovered_count": str(report.discovered_count),
            },
        )


def build_default_registry() -> dict[str, Pipeline]:
    """Build the exact MVP command registry."""

    return {
        "init": Pipeline(name="init", steps=[InitProjectStep()]),
        "wizard": Pipeline(name="wizard", steps=[WizardStep()]),
        "verify": Pipeline(name="verify", steps=[VerifyBlueprintStep()]),
        "lock": Pipeline(name="lock", steps=[AuthorityLockStep()]),
        "unlock": Pipeline(name="unlock", steps=[AuthorityUnlockStep()]),
        "status": Pipeline(name="status", steps=[AuthorityStatusStep()]),
    }
