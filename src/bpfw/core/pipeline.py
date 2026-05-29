"""Pipeline types and stable execution helpers."""

from dataclasses import dataclass
from typing import Protocol

from bpfw.core.context import ProjectContext
from bpfw.core.result import ResultStatus, StepResult


class PipelineStep(Protocol):
    """Contract implemented by every pipeline step."""

    name: str

    def run(self, context: ProjectContext) -> StepResult:
        """Execute a stable unit of validation/work."""


@dataclass(slots=True)
class Pipeline:
    """Ordered list of stable steps."""

    name: str
    steps: list[PipelineStep]



def execute_pipeline(pipeline: Pipeline, context: ProjectContext) -> list[StepResult]:
    """Run steps in order and stop when a blocking result is produced."""

    step_results: list[StepResult] = []
    for step in pipeline.steps:
        step_result = step.run(context)
        step_results.append(step_result)
        if step_result.status in {ResultStatus.BLOCK, ResultStatus.CRITICAL}:
            break
    return step_results
