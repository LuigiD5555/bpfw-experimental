"""Command registry for BPFW MVP Catalog Mode."""

from dataclasses import dataclass

from bpfw.catalog.paths import CANONICAL_BLUEPRINT_FILE
from bpfw.catalog.verify import run_verify
from bpfw.catalog.wizard import complete_human_fields
from bpfw.catalog.writer import run_init
from bpfw.core.pipeline import Pipeline, PipelineStep
from bpfw.core.result import ResultStatus, StepResult
from bpfw.protection.authority import (
    get_blueprint_lock_state,
    lock_blueprint,
    setup_blueprint_protection,
    unlock_blueprint,
)


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
        if get_blueprint_lock_state(project_root=context.project_root) == "locked":
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
        lock_state = lock_blueprint(project_root=context.project_root)
        if lock_state == "unknown":
            return StepResult(
                status=ResultStatus.BLOCK,
                message=f"BPFW blueprint does not exist: {CANONICAL_BLUEPRINT_FILE}. Run bpfw init first.",
                source=self.name,
                details={"lock_state": lock_state, "resource_id": "project_blueprint"},
            )
        if lock_state == "unsupported":
            return StepResult(
                status=ResultStatus.BLOCK,
                message=(
                    "BPFW could not enforce an OS lock for "
                    f"{CANONICAL_BLUEPRINT_FILE}. Run with sudo on a filesystem "
                    "that supports ownership changes or immutable flags."
                ),
                source=self.name,
                details={"lock_state": lock_state, "resource_id": "project_blueprint"},
            )

        return StepResult(
            status=ResultStatus.OK,
            message=f"Blueprint locked: {CANONICAL_BLUEPRINT_FILE}",
            source=self.name,
            details={"lock_state": lock_state, "resource_id": "project_blueprint"},
        )


@dataclass(slots=True)
class AuthorityProtectSetupStep(PipelineStep):
    """Prepare OS-level protection for the MVP blueprint resource."""

    name: str = "protection.setup"

    def run(self, context) -> StepResult:  # noqa: ANN001
        lock_state = setup_blueprint_protection(project_root=context.project_root)
        if lock_state == "unknown":
            return StepResult(
                status=ResultStatus.BLOCK,
                message=f"BPFW blueprint does not exist: {CANONICAL_BLUEPRINT_FILE}. Run bpfw init first.",
                source=self.name,
                details={"lock_state": lock_state, "resource_id": "project_blueprint"},
            )
        if lock_state == "unsupported":
            return StepResult(
                status=ResultStatus.BLOCK,
                message=(
                    "BPFW could not prepare OS protection for "
                    f"{CANONICAL_BLUEPRINT_FILE}. Use a terminal where sudo can run "
                    "or move the project to a filesystem that supports ownership "
                    "changes or immutable flags."
                ),
                source=self.name,
                details={"lock_state": lock_state, "resource_id": "project_blueprint"},
            )

        return StepResult(
            status=ResultStatus.OK,
            message=f"Blueprint protection enabled: {CANONICAL_BLUEPRINT_FILE}",
            source=self.name,
            details={"lock_state": lock_state, "resource_id": "project_blueprint"},
        )


@dataclass(slots=True)
class AuthorityUnlockStep(PipelineStep):
    """Unlock the MVP blueprint resource."""

    name: str = "protection.unlock"

    def run(self, context) -> StepResult:  # noqa: ANN001
        lock_state = unlock_blueprint(project_root=context.project_root)
        if lock_state == "unknown":
            return StepResult(
                status=ResultStatus.BLOCK,
                message=f"BPFW blueprint does not exist: {CANONICAL_BLUEPRINT_FILE}. Run bpfw init first.",
                source=self.name,
                details={"lock_state": lock_state, "resource_id": "project_blueprint"},
            )

        return StepResult(
            status=ResultStatus.OK,
            message=f"Blueprint unlocked: {CANONICAL_BLUEPRINT_FILE}",
            source=self.name,
            details={"resource_id": "project_blueprint", "lock_state": lock_state},
        )


@dataclass(slots=True)
class AuthorityStatusStep(PipelineStep):
    """Report compact MVP status for engine callers."""

    name: str = "catalog.status"

    def run(self, context) -> StepResult:  # noqa: ANN001
        report, _exit_code = run_verify(project_root=context.project_root)
        lock_state = get_blueprint_lock_state(project_root=context.project_root)
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
        "protect.setup": Pipeline(name="protect.setup", steps=[AuthorityProtectSetupStep()]),
        "lock": Pipeline(name="lock", steps=[AuthorityLockStep()]),
        "unlock": Pipeline(name="unlock", steps=[AuthorityUnlockStep()]),
        "status": Pipeline(name="status", steps=[AuthorityStatusStep()]),
    }
