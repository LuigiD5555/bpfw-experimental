"""PURPOSE pipeline types and stable execution helpers
DOMAIN  framework core
"""

from dataclasses import dataclass
from typing import Protocol

from bpfw.core.context import ProjectContext
from bpfw.core.result import ResultStatus, StepResult


class PipelineStep(Protocol):
    """PURPOSE contract implemented by every pipeline step
    DOMAIN  framework core
    """

    name: str

    def run(self, context: ProjectContext) -> StepResult:
        """PURPOSE execute a stable unit of check/work
        DOMAIN  framework core
        """


@dataclass(slots=True)
class Pipeline:
    """PURPOSE ordered list of stable steps
    DOMAIN  framework core
    """

    name: str
    steps: list[PipelineStep]



def execute_pipeline(pipeline: Pipeline, context: ProjectContext) -> list[StepResult]:
    """PURPOSE run steps in order and stop when a blocking result is produced
    DOMAIN  framework core
    """

    step_results: list[StepResult] = []
    for step in pipeline.steps:
        step_result = step.run(context)
        step_results.append(step_result)
        if step_result.status in {ResultStatus.BLOCK, ResultStatus.CRITICAL}:
            break
    return step_results
