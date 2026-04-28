"""Command registry for BPFW engine pipelines."""

from __future__ import annotations

from dataclasses import dataclass

from bpfw.architecture.architecture_validator import validate_architecture
from bpfw.blueprint.snapshot import build_snapshot
from bpfw.blueprint.validator import validate_blueprint
from bpfw.core.pipeline import Pipeline, PipelineStep
from bpfw.core.result import ResultStatus, StepResult


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



def build_default_registry() -> dict[str, Pipeline]:
    """Create base command to pipeline mapping."""

    verify_pipeline = Pipeline(
        name="verify",
        steps=[VerifyBlueprintStep(), VerifyArchitectureStep()],
    )
    architecture_check_pipeline = Pipeline(
        name="architecture_check",
        steps=[VerifyArchitectureStep()],
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
        "discover": bootstrap_pipeline,
        "review": bootstrap_pipeline,
        "apply": bootstrap_pipeline,
        "status": bootstrap_pipeline,
    }
