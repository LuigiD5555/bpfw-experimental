"""Deterministic engine orchestrating BPFW pipelines."""

from pathlib import Path

from bpfw.core.context import EngineCommand, build_project_context
from bpfw.core.pipeline import execute_pipeline
from bpfw.core import registry as core_registry
from bpfw.core.registry import VerifyBlueprintStep, build_default_registry
from bpfw.core.result import EngineResult, ResultStatus, StepResult, aggregate_status
from bpfw.integrations.registry import IntegrationRegistry


class BlueprintEngine:
    """Minimal engine implementation for MVP catalog mode."""

    def __init__(self, integration_registry: IntegrationRegistry | None = None) -> None:
        self._registry = build_default_registry(integration_registry=integration_registry)

    def run(self, command: EngineCommand) -> EngineResult:
        """Execute command against registry pipeline."""

        pipeline = self._registry.get(command.command_name)
        if pipeline is None:
            return EngineResult(
                command_name=command.command_name,
                status=ResultStatus.BLOCK,
                steps=[
                    StepResult(
                        status=ResultStatus.BLOCK,
                        message=f"Unknown command: {command.command_name}",
                        source="core.registry",
                        suggested_actions=[
                            "Use one of: init, inspector, editor, planner, verify, lock, unlock, status"
                        ],
                    )
                ],
            )

        context = build_project_context(
            project_root=command.project_root,
            command_arguments=command.arguments,
        )
        step_results = []
        if command.command_name in {"inspector", "editor", "planner"}:
            lock_state = core_registry.get_authority_protection_status(project_root=context.project_root).status
            if lock_state in {"locked", "degraded"}:
                verify_result = VerifyBlueprintStep().run(context)
                step_results.append(verify_result)
                if verify_result.status in {ResultStatus.BLOCK, ResultStatus.CRITICAL}:
                    return EngineResult(
                        command_name=command.command_name,
                        status=aggregate_status(step_results),
                        steps=step_results,
                    )
        step_results.extend(execute_pipeline(pipeline=pipeline, context=context))
        return EngineResult(
            command_name=command.command_name,
            status=aggregate_status(step_results),
            steps=step_results,
        )


def build_command(command_name: str, project_root: Path, arguments: dict[str, str]) -> EngineCommand:
    """Normalize runtime arguments into EngineCommand."""

    return EngineCommand(command_name=command_name, project_root=project_root, arguments=arguments)
