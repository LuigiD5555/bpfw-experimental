"""Pipeline types and deterministic execution helpers."""

from dataclasses import dataclass
from typing import Protocol

from bpfw.core.context import ProjectContext
from bpfw.core.result import StepResult


class PipelineStep(Protocol):
    """Contract implemented by every pipeline step."""

    name: str

    def run(self, context: ProjectContext) -> StepResult:
        """Execute a deterministic unit of validation/work."""


@dataclass(slots=True)
class Pipeline:
    """Ordered list of deterministic steps."""

    name: str
    steps: list[PipelineStep]



def execute_pipeline(pipeline: Pipeline, context: ProjectContext) -> list[StepResult]:
    """Run all steps in order and collect results."""

    return [step.run(context) for step in pipeline.steps]
