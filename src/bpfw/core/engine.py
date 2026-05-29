"""Deterministic engine orchestrating BPFW pipelines."""

from pathlib import Path

from bpfw.core.context import EngineCommand, build_project_context
from bpfw.core.pipeline import execute_pipeline
from bpfw.core import registry as core_registry
from bpfw.core.registry import VerifyBlueprintStep, build_default_registry
from bpfw.core.result import EngineResult, ResultStatus, StepResult, aggregate_status
from bpfw.integrations.registry import IntegrationRegistry
from bpfw.core.profiling import RuntimeProfiler

_profiler = RuntimeProfiler()


def _is_incomplete_only_verify_block(verify_result: StepResult) -> bool:
    """Return whether verify is blocked only by incomplete metadata in draft authority."""

    if verify_result.status not in {ResultStatus.BLOCK, ResultStatus.CRITICAL}:
        return False

    details = verify_result.details
    return (
        details.get("authority_state") == "draft"
        and details.get("incomplete_blocks") not in {None, "", "0"}
        and details.get("missing_declared_code") in {None, "", "0"}
        and details.get("undeclared_code") in {None, "", "0"}
        and details.get("duplicate_active_purposes") in {None, "", "0"}
        and details.get("invalid_statuses") in {None, "", "0"}
    )


def _is_root_blocks_only_verify_block(verify_result: StepResult) -> bool:
    """Return whether verify is blocked only by root-level blocks in blueprint.yaml."""

    if verify_result.status not in {ResultStatus.BLOCK, ResultStatus.CRITICAL}:
        return False
    message = (verify_result.message or "").strip()
    return message.startswith("Root blueprint.yaml contains ") and "Blocks must be in shard files only." in message


class BlueprintEngine:
    """Minimal engine implementation for catalog mode."""

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
                            "Use one of: init, inspector, editor, planner, diff, verify, lock, unlock, status"
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
            with _profiler.measure("engine.preflight_lock_check"):
                lock_state = core_registry.get_authority_protection_status(project_root=context.project_root).status
            if lock_state in {"locked", "degraded"}:
                with _profiler.measure("engine.verify_for_interactive"):
                    verify_result = VerifyBlueprintStep().run(context)
                if _is_incomplete_only_verify_block(verify_result=verify_result):
                    verify_result = StepResult(
                        status=ResultStatus.WARNING,
                        message=verify_result.message,
                        source=verify_result.source,
                        details=verify_result.details,
                        affected_resources=verify_result.affected_resources,
                        suggested_actions=verify_result.suggested_actions,
                    )
                elif _is_root_blocks_only_verify_block(verify_result=verify_result):
                    verify_result = StepResult(
                        status=ResultStatus.WARNING,
                        message=verify_result.message,
                        source=verify_result.source,
                        details=verify_result.details,
                        affected_resources=verify_result.affected_resources,
                        suggested_actions=verify_result.suggested_actions,
                    )
                step_results.append(verify_result)
                if verify_result.status in {ResultStatus.BLOCK, ResultStatus.CRITICAL}:
                    return EngineResult(
                        command_name=command.command_name,
                        status=aggregate_status(step_results),
                        steps=step_results,
                    )
        with _profiler.measure("engine.integration_dispatch"):
            step_results.extend(execute_pipeline(pipeline=pipeline, context=context))
        return EngineResult(
            command_name=command.command_name,
            status=aggregate_status(step_results),
            steps=step_results,
        )


def build_command(command_name: str, project_root: Path, arguments: dict[str, str]) -> EngineCommand:
    """Normalize runtime arguments into EngineCommand."""

    return EngineCommand(command_name=command_name, project_root=project_root, arguments=arguments)
