"""Result contracts produced by engine and steps."""

from dataclasses import dataclass, field
from enum import StrEnum


class ResultStatus(StrEnum):
    """Normalized status values for every engine result."""

    OK = "OK"
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCK = "BLOCK"
    CRITICAL = "CRITICAL"


@dataclass(slots=True)
class StepResult:
    """Single step outcome with evidence payload."""

    status: ResultStatus
    message: str
    source: str
    details: dict[str, str] = field(default_factory=dict)
    affected_resources: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EngineResult:
    """Aggregated output for one executed command."""

    command_name: str
    status: ResultStatus
    steps: list[StepResult]


_STATUS_PRIORITY: dict[ResultStatus, int] = {
    ResultStatus.OK: 0,
    ResultStatus.INFO: 1,
    ResultStatus.WARNING: 2,
    ResultStatus.BLOCK: 3,
    ResultStatus.CRITICAL: 4,
}



def aggregate_status(step_results: list[StepResult]) -> ResultStatus:
    """Compute final status using the strongest step severity."""

    if not step_results:
        return ResultStatus.INFO
    return max(step_results, key=lambda item: _STATUS_PRIORITY[item.status]).status
