"""Deterministic engine orchestrating BPFW pipelines."""

from __future__ import annotations

from pathlib import Path

from bpfw.core.context import EngineCommand, build_project_context
from bpfw.core.pipeline import execute_pipeline
from bpfw.core.registry import build_default_registry
from bpfw.core.result import EngineResult, ResultStatus, StepResult, aggregate_status


class BlueprintEngine:
    """Minimal engine implementation for Prompt 0 project bootstrap."""

    def __init__(self) -> None:
        self._registry = build_default_registry()

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
                            "Use one of: verify, verify_integrity, manifest_write, runtime snapshot, wiring check, architecture check, composition check, discover, review, apply, status"
                        ],
                    )
                ],
            )

        context = build_project_context(command.project_root)
        step_results = execute_pipeline(pipeline=pipeline, context=context)
        return EngineResult(
            command_name=command.command_name,
            status=aggregate_status(step_results),
            steps=step_results,
        )



def build_command(command_name: str, project_root: Path, arguments: dict[str, str]) -> EngineCommand:
    """Normalize runtime arguments into EngineCommand."""

    return EngineCommand(command_name=command_name, project_root=project_root, arguments=arguments)
