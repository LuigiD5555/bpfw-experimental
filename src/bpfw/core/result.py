"""PURPOSE result contracts produced by engine and steps
DOMAIN  framework core
"""

from dataclasses import dataclass, field
from enum import StrEnum


class ResultStatus(StrEnum):
    """PURPOSE clean status values for every engine result
    DOMAIN  framework core
    """

    OK = "OK"
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCK = "BLOCK"
    CRITICAL = "CRITICAL"


@dataclass(slots=True)
class StepResult:
    """PURPOSE single step outcome with evidence data
        DOMAIN  framework core

    """

    status: ResultStatus
    message: str
    source: str
    details: dict[str, str] = field(default_factory=dict)
    affected_resources: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EngineResult:
    """PURPOSE aggregated output for one executed command
    DOMAIN  framework core
    """

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
    """PURPOSE calculate final status using the strongest step severity
    DOMAIN  framework core
    """

    if not step_results:
        return ResultStatus.INFO
    return max(step_results, key=lambda item: _STATUS_PRIORITY[item.status]).status
