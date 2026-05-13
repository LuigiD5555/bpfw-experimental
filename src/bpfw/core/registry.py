"""Command registry for BPFW MVP Catalog Mode."""

from dataclasses import dataclass

from bpfw.catalog.paths import CANONICAL_BLUEPRINT_FILE
from bpfw.catalog.verify import run_verify
from bpfw.catalog.writer import run_init
from bpfw.core.pipeline import Pipeline, PipelineStep
from bpfw.core.result import ResultStatus, StepResult
from bpfw.integrations.registry import (
    IntegrationRegistry,
    build_default_integration_registry,
)
from bpfw.protection.authority import (
    MISSING_BLUEPRINT_STATUS,
    get_blueprint_lock_state,
    lock_authority,
    unlock_authority,
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
class IntegrationStep(PipelineStep):
    """Run a named optional BPFW integration."""

    integration_registry: IntegrationRegistry
    integration_name: str
    name: str

    def run(self, context) -> StepResult:  # noqa: ANN001
        lock_state = get_blueprint_lock_state(project_root=context.project_root)
        if self.integration_name in {"inspector", "editor", "planner"} and lock_state in {"locked", "degraded"}:
            unlock_result = unlock_authority(project_root=context.project_root)
            if unlock_result.status != "unlocked":
                return StepResult(
                    status=ResultStatus.BLOCK,
                    message=(
                        "BLOCK: Blueprint is locked and automatic unlock failed. "
                        "Run bpfw unlock before editing authority data."
                    ),
                    source=self.name,
                    details={
                        "error_code": "AUTHORITY_LOCKED",
                        "lock_state": lock_state,
                        "unlock_status": unlock_result.status,
                    },
                    suggested_actions=["Run bpfw unlock"],
                )

        result = self.integration_registry.run(
            name=self.integration_name,
            project_root=context.project_root,
        )
        return StepResult(
            status=ResultStatus.OK if result.success else ResultStatus.BLOCK,
            message=result.message,
            source=self.name,
            details={"integration": self.integration_name},
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
            "duplicate_active_purposes": str(report.duplicate_active_intent_count),
            "invalid_statuses": str(report.invalid_lifecycle_count),
            "incomplete_blocks": str(report.incomplete_responsibility_count),
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
    """Lock the MVP authority resources."""

    name: str = "protection.lock"

    def run(self, context) -> StepResult:  # noqa: ANN001
        lock_result = lock_authority(project_root=context.project_root)
        if lock_result.status == MISSING_BLUEPRINT_STATUS:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=f"BPFW blueprint does not exist: {CANONICAL_BLUEPRINT_FILE}. Run bpfw init first.",
                source=self.name,
                details={"lock_state": lock_result.status, "resource_id": "authority"},
            )
        if lock_result.status == "unsupported":
            return StepResult(
                status=ResultStatus.BLOCK,
                message=(
                    "BPFW could not enforce an OS lock for "
                    "authority resources. Run with sudo on a filesystem "
                    "that supports ownership changes or immutable flags."
                ),
                source=self.name,
                details={"lock_state": lock_result.status, "resource_id": "authority"},
            )

        return StepResult(
            status=ResultStatus.OK,
            message="Authority locked",
            source=self.name,
            details={"lock_state": lock_result.status, "resource_id": "authority"},
        )


@dataclass(slots=True)
class AuthorityProtectSetupStep(PipelineStep):
    """Hidden compatibility alias for the lock pipeline."""

    name: str = "protection.setup"

    def run(self, context) -> StepResult:  # noqa: ANN001
        lock_result = lock_authority(project_root=context.project_root)
        lock_state = lock_result.status
        if lock_state == MISSING_BLUEPRINT_STATUS:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=f"BPFW blueprint does not exist: {CANONICAL_BLUEPRINT_FILE}. Run bpfw init first.",
                source=self.name,
                details={
                    "lock_state": lock_state,
                    "resource_id": "authority",
                },
            )
        if lock_state == "unsupported":
            return StepResult(
                status=ResultStatus.BLOCK,
                message=(
                    "BPFW could not prepare OS protection for "
                    "authority resources. Use a terminal where sudo can run "
                    "or move the project to a filesystem that supports ownership "
                    "changes or immutable flags."
                ),
                source=self.name,
                details={
                    "lock_state": lock_state,
                    "resource_id": "authority",
                },
            )

        return StepResult(
            status=ResultStatus.OK,
            message="Authority locked",
            source=self.name,
            details={
                "lock_state": lock_state,
                "resource_id": "authority",
            },
        )


@dataclass(slots=True)
class AuthorityUnlockStep(PipelineStep):
    """Unlock the MVP authority resources."""

    name: str = "protection.unlock"

    def run(self, context) -> StepResult:  # noqa: ANN001
        unlock_result = unlock_authority(project_root=context.project_root)
        if unlock_result.status == MISSING_BLUEPRINT_STATUS:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=f"BPFW blueprint does not exist: {CANONICAL_BLUEPRINT_FILE}. Run bpfw init first.",
                source=self.name,
                details={"lock_state": unlock_result.status, "resource_id": "authority"},
            )

        return StepResult(
            status=ResultStatus.OK,
            message="Authority unlocked",
            source=self.name,
            details={"resource_id": "authority", "lock_state": unlock_result.status},
        )


@dataclass(slots=True)
class AuthorityStatusStep(PipelineStep):
    """Report compact MVP status for engine callers."""

    name: str = "catalog.status"

    def run(self, context) -> StepResult:  # noqa: ANN001
        report, _exit_code = run_verify(project_root=context.project_root)
        lock_state = get_blueprint_lock_state(project_root=context.project_root)
        drift_state = "drift" if report.missing_declared_count or report.undeclared_count else "clean"
        status_state = "invalid" if report.invalid_lifecycle_count else "valid"

        return StepResult(
            status=ResultStatus.OK if report.allowed else ResultStatus.BLOCK,
            message="MVP status reported",
            source=self.name,
            details={
                "lock": lock_state,
                "blueprint_state": report.authority_state,
                "drift_state": drift_state,
                "status_state": status_state,
                "declared_count": str(report.declared_count),
                "discovered_count": str(report.discovered_count),
            },
        )


def build_default_registry(
    integration_registry: IntegrationRegistry | None = None,
) -> dict[str, Pipeline]:
    """Build the exact MVP command registry."""

    optional_integrations = integration_registry or build_default_integration_registry()
    return {
        "init": Pipeline(name="init", steps=[InitProjectStep()]),
        "inspector": Pipeline(
            name="inspector",
            steps=[
                IntegrationStep(
                    integration_registry=optional_integrations,
                    integration_name="inspector",
                    name="integrations.inspector",
                ),
            ],
        ),
        "editor": Pipeline(
            name="editor",
            steps=[
                IntegrationStep(
                    integration_registry=optional_integrations,
                    integration_name="editor",
                    name="integrations.editor",
                ),
            ],
        ),
        "planner": Pipeline(
            name="planner",
            steps=[
                IntegrationStep(
                    integration_registry=optional_integrations,
                    integration_name="planner",
                    name="integrations.planner",
                ),
            ],
        ),
        "verify": Pipeline(name="verify", steps=[VerifyBlueprintStep()]),
        "protect.setup": Pipeline(name="protect.setup", steps=[AuthorityProtectSetupStep()]),
        "lock": Pipeline(name="lock", steps=[AuthorityLockStep()]),
        "unlock": Pipeline(name="unlock", steps=[AuthorityUnlockStep()]),
        "status": Pipeline(name="status", steps=[AuthorityStatusStep()]),
    }
