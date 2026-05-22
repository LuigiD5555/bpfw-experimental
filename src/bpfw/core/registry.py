"""Command registry for BPFW MVP Catalog Mode."""

from dataclasses import dataclass

from bpfw.catalog.paths import CANONICAL_BLUEPRINT_FILE
from bpfw.catalog.verify import run_verify
from bpfw.catalog.writer import run_init
from bpfw.core.pipeline import Pipeline, PipelineStep
from bpfw.core.result import ResultStatus, StepResult
from bpfw.core.errors import BlueprintLockedError
from bpfw.integrations.registry import (
    IntegrationRegistry,
    build_default_integration_registry,
)
from bpfw.protection.authority import (
    MISSING_BLUEPRINT_STATUS,
    get_authority_protection_status,
    lock_authority,
    unlock_authority,
)
from bpfw.protection.runtime_lease import runtime_blueprint_write_lease


@dataclass(slots=True)
class InitProjectStep(PipelineStep):
    """Initialize the catalog blueprint file."""

    name: str = "catalog.init"

    def run(self, context) -> StepResult:  # noqa: ANN001
        try:
            with runtime_blueprint_write_lease(
                project_root=context.project_root,
                tool_name="init",
            ):
                _success, message, exit_code = run_init(project_root=context.project_root)
        except BlueprintLockedError as error:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=f"BLOCK: {error}",
                source=self.name,
                details={"blueprint_path": CANONICAL_BLUEPRINT_FILE},
            )
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
        from bpfw.integrations.shared.runtime_context import (
            set_integration_runtime_cache,
            clear_integration_runtime_cache,
        )
        
        try:
            # Pass runtime cache to integration
            set_integration_runtime_cache(context.runtime_cache)
            
            with runtime_blueprint_write_lease(
                project_root=context.project_root,
                tool_name=self.integration_name,
            ) as lease:
                result = self.integration_registry.run(
                    name=self.integration_name,
                    project_root=context.project_root,
                    command_arguments=context.command_arguments,
                )
                
            # Clear runtime cache after integration completes
            clear_integration_runtime_cache()
        except BlueprintLockedError as error:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=f"BLOCK: {error}",
                source=self.name,
                details={
                    "error_code": "AUTHORITY_LOCKED",
                    "integration": self.integration_name,
                },
                suggested_actions=[
                    "Run in an interactive terminal and approve temporary unlock",
                    "or run bpfw unlock manually before editing authority data",
                ],
            )

        message = result.message
        if lease.relock_warning:
            message = f"{message}\n\n{lease.relock_warning}"

        return StepResult(
            status=ResultStatus.OK if result.success else ResultStatus.BLOCK,
            message=message,
            source=self.name,
            details={"integration": self.integration_name},
        )


@dataclass(slots=True)
class VerifyBlueprintStep(PipelineStep):
    """Run the canonical catalog verify pipeline."""

    name: str = "catalog.verify"

    def run(self, context) -> StepResult:  # noqa: ANN001
        from bpfw.catalog.loader import BlueprintLoader
        from bpfw.catalog.verify import scan_project_from_blueprint
        from bpfw.core.profiling import RuntimeProfiler
        
        profiler = RuntimeProfiler()
        
        with profiler.measure("engine.load_blueprint"):
            # Load blueprint data for scan
            loader = BlueprintLoader(project_root=context.project_root)
            load_result = loader.load()
        
        with profiler.measure("engine.scan_project"):
            # Cache scan result in context runtime_cache
            if load_result.state not in {"missing", "invalid"}:
                scan_result = scan_project_from_blueprint(
                    project_root=context.project_root,
                    blueprint_data=load_result.data,
                )
                context.runtime_cache["scan_result"] = scan_result
                context.runtime_cache["blueprint_data"] = load_result.data
            else:
                scan_result = None
                context.runtime_cache["scan_result"] = None
                context.runtime_cache["blueprint_data"] = None
        
        with profiler.measure("engine.run_verify"):
            report, exit_code = run_verify(
                project_root=context.project_root,
                precomputed_scan_result=scan_result,
            )
        
        # Cache the verification report
        context.runtime_cache["verify_report"] = report
        
        block_findings = [finding for finding in report.findings if finding.severity == "block"]
        details = {
            "authority_state": report.authority_state,
            "declared_count": str(report.declared_count),
            "discovered_count": str(report.discovered_count),
            "missing_declared_code": str(report.missing_declared_count),
            "undeclared_code": str(report.undeclared_count),
            "duplicate_active_purposes": str(report.duplicate_active_purpose_count),
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
                    "that supports ownership changes, immutable flags, or read-only permissions."
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
        from bpfw.core.profiling import RuntimeProfiler
        
        profiler = RuntimeProfiler()
        
        with profiler.measure("status.run_verify"):
            report, _exit_code = run_verify(project_root=context.project_root)
        
        lock_state = get_authority_protection_status(project_root=context.project_root).status
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

        "diff": Pipeline(
            name="diff",
            steps=[
                IntegrationStep(
                    integration_registry=optional_integrations,
                    integration_name="diff",
                    name="integrations.diff",
                ),
            ],
        ),
        "verify": Pipeline(name="verify", steps=[VerifyBlueprintStep()]),
        "lock": Pipeline(name="lock", steps=[AuthorityLockStep()]),
        "unlock": Pipeline(name="unlock", steps=[AuthorityUnlockStep()]),
        "status": Pipeline(name="status", steps=[AuthorityStatusStep()]),
    }
