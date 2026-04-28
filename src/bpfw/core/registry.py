"""Command registry for BPFW engine pipelines."""

from __future__ import annotations

from dataclasses import dataclass

from bpfw.architecture.architecture_validator import validate_architecture
from bpfw.blueprint.snapshot import build_snapshot
from bpfw.blueprint.validator import validate_blueprint
from bpfw.composition.checker import validate_composition
from bpfw.core.pipeline import Pipeline, PipelineStep
from bpfw.core.result import ResultStatus, StepResult
from bpfw.runtime.collector import collect_runtime_snapshot
from bpfw.runtime.snapshot import snapshot_to_dict, snapshot_to_human_lines, snapshot_to_json
from bpfw.wiring.verifier import verify_wiring


@dataclass(slots=True)
class StaticStep(PipelineStep):
    """Prompt 0 placeholder step used to keep the engine executable."""

    name: str
    message: str

    def run(self, context) -> StepResult:  # noqa: ANN001
        del context
        return StepResult(
            status=ResultStatus.WARNING,
            message=self.message,
            source=self.name,
            details={"implementation_state": "not_implemented"},
            suggested_actions=["Implement concrete validators in next prompts"],
        )


@dataclass(slots=True)
class VerifyBlueprintStep(PipelineStep):
    """Executable verify step for blueprint authority validation."""

    name: str = "blueprint.verify"

    def run(self, context) -> StepResult:  # noqa: ANN001
        validation_result = validate_blueprint(project_root=context.project_root)
        if validation_result.is_valid and validation_result.blueprint is not None:
            snapshot = build_snapshot(validation_result.blueprint)
            return StepResult(
                status=ResultStatus.OK,
                message="Blueprint loaded and validated successfully",
                source=self.name,
                details={
                    "responsibility_count": str(snapshot.responsibility_count),
                    "blueprint_path": snapshot.blueprint_path,
                },
            )

        first_error = validation_result.errors[0]
        return StepResult(
            status=ResultStatus.BLOCK,
            message=first_error.message,
            source=self.name,
            details={"error_code": first_error.code},
            affected_resources=[first_error.file_path],
            suggested_actions=[first_error.recommendation],
        )


@dataclass(slots=True)
class VerifyArchitectureStep(PipelineStep):
    """Executable architecture step for layer and import validation."""

    name: str = "architecture.check"

    def run(self, context) -> StepResult:  # noqa: ANN001
        validation_result = validate_architecture(project_root=context.project_root)
        if validation_result.errors:
            first_error = validation_result.errors[0]
            return StepResult(
                status=ResultStatus.BLOCK,
                message=first_error.message,
                source=self.name,
                details={"error_code": first_error.code},
                affected_resources=[first_error.file_path],
                suggested_actions=[first_error.recommendation],
            )

        if validation_result.warnings:
            first_warning = validation_result.warnings[0]
            return StepResult(
                status=ResultStatus.WARNING,
                message=first_warning.message,
                source=self.name,
                details={"error_code": first_warning.code},
                affected_resources=[first_warning.file_path],
                suggested_actions=[first_warning.recommendation],
            )

        profile_id = ""
        if validation_result.profile is not None:
            profile_id = validation_result.profile.profile_id
        return StepResult(
            status=ResultStatus.OK,
            message="Architecture profile loaded and import rules validated successfully",
            source=self.name,
            details={"architecture_profile_id": profile_id},
        )


@dataclass(slots=True)
class VerifyCompositionStep(PipelineStep):
    """Executable composition step for concrete wiring checks."""

    name: str = "composition.check"

    def run(self, context) -> StepResult:  # noqa: ANN001
        validation_result = validate_composition(project_root=context.project_root)
        if validation_result.errors:
            first_error = validation_result.errors[0]
            return StepResult(
                status=ResultStatus.BLOCK,
                message=first_error.message,
                source=self.name,
                details={"error_code": first_error.code},
                affected_resources=[first_error.file_path],
                suggested_actions=[first_error.recommendation],
            )

        return StepResult(
            status=ResultStatus.OK,
            message="Composition roots validated successfully",
            source=self.name,
        )


@dataclass(slots=True)
class VerifyRuntimeSnapshotStep(PipelineStep):
    """Executable runtime snapshot step for active binding visibility."""

    name: str = "runtime.snapshot"

    def run(self, context) -> StepResult:  # noqa: ANN001
        collection_result = collect_runtime_snapshot(project_root=context.project_root)
        if collection_result.errors:
            first_error = collection_result.errors[0]
            return StepResult(
                status=ResultStatus.BLOCK,
                message=first_error.message,
                source=self.name,
                details={
                    "error_code": first_error.code,
                },
                affected_resources=[first_error.file_path],
                suggested_actions=[first_error.recommendation],
            )

        if collection_result.snapshot is None:
            return StepResult(
                status=ResultStatus.WARNING,
                message="Runtime snapshot could not be collected",
                source=self.name,
                details={"runtime_snapshot": "{}"},
                suggested_actions=["Declare runtime bindings metadata in wiring or .bpfw/runtime_bindings.yaml"],
            )

        snapshot = collection_result.snapshot
        warning_count = len(collection_result.warnings)
        if warning_count > 0:
            first_warning = collection_result.warnings[0]
            return StepResult(
                status=ResultStatus.WARNING,
                message=first_warning.message,
                source=self.name,
                details={
                    "warning_code": first_warning.code,
                    "runtime_snapshot_json": snapshot_to_json(snapshot),
                    "runtime_snapshot_human": snapshot_to_human_lines(snapshot),
                    "warning_count": str(warning_count),
                },
                affected_resources=[first_warning.file_path],
                suggested_actions=[first_warning.recommendation],
            )

        return StepResult(
            status=ResultStatus.OK,
            message="Runtime snapshot collected successfully",
            source=self.name,
            details={
                "runtime_snapshot_json": snapshot_to_json(snapshot),
                "runtime_snapshot_human": snapshot_to_human_lines(snapshot),
                "active_bindings_count": str(len(snapshot_to_dict(snapshot)["active_bindings"])),
            },
        )


@dataclass(slots=True)
class VerifyWiringStep(PipelineStep):
    """Executable wiring step for blueprint/runtime active implementation alignment."""

    name: str = "wiring.check"

    def run(self, context) -> StepResult:  # noqa: ANN001
        verification_result = verify_wiring(project_root=context.project_root)
        if verification_result.issues:
            first_issue = verification_result.issues[0]
            status = ResultStatus.WARNING
            if first_issue.severity == "block":
                status = ResultStatus.BLOCK
            elif first_issue.severity == "critical":
                status = ResultStatus.CRITICAL

            if any(issue.severity == "critical" for issue in verification_result.issues):
                status = ResultStatus.CRITICAL
            elif any(issue.severity == "block" for issue in verification_result.issues):
                status = ResultStatus.BLOCK

            return StepResult(
                status=status,
                message=first_issue.message,
                source=self.name,
                details={
                    "error_code": first_issue.code,
                    "wiring_issue_count": str(len(verification_result.issues)),
                },
                affected_resources=[first_issue.file_path],
                suggested_actions=[first_issue.recommendation],
            )

        return StepResult(
            status=ResultStatus.OK,
            message="Wiring verification passed",
            source=self.name,
            details={
                "active_bindings_count": str(len(verification_result.active_bindings)),
            },
        )



def build_default_registry() -> dict[str, Pipeline]:
    """Create base command to pipeline mapping."""

    verify_pipeline = Pipeline(
        name="verify",
        steps=[
            VerifyBlueprintStep(),
            VerifyArchitectureStep(),
            VerifyCompositionStep(),
            VerifyRuntimeSnapshotStep(),
            VerifyWiringStep(),
        ],
    )
    architecture_check_pipeline = Pipeline(
        name="architecture_check",
        steps=[VerifyArchitectureStep()],
    )
    composition_check_pipeline = Pipeline(
        name="composition_check",
        steps=[VerifyCompositionStep()],
    )
    runtime_snapshot_pipeline = Pipeline(
        name="runtime_snapshot",
        steps=[VerifyRuntimeSnapshotStep()],
    )
    wiring_check_pipeline = Pipeline(
        name="wiring_check",
        steps=[VerifyWiringStep()],
    )
    bootstrap_pipeline = Pipeline(
        name="bootstrap",
        steps=[
            StaticStep(
                name="blueprint.authority",
                message="Blueprint authority validation is not implemented yet",
            ),
            StaticStep(
                name="architecture.profile",
                message="Architecture profile validation is not implemented yet",
            ),
            StaticStep(
                name="lifecycle.rules",
                message="Lifecycle validation is not implemented yet",
            ),
        ],
    )
    return {
        "verify": verify_pipeline,
        "architecture_check": architecture_check_pipeline,
        "composition_check": composition_check_pipeline,
        "runtime_snapshot": runtime_snapshot_pipeline,
        "wiring_check": wiring_check_pipeline,
        "discover": bootstrap_pipeline,
        "review": bootstrap_pipeline,
        "apply": bootstrap_pipeline,
        "status": bootstrap_pipeline,
    }
