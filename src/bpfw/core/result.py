"""Result contracts produced by engine and steps."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, TypeVar


class ResultStatus(StrEnum):
    """Normalized status values for every engine result."""

    OK = "OK"
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCK = "BLOCK"
    CRITICAL = "CRITICAL"


@dataclass(slots=True)
class StepResult:
    """Single step outcome with evidence data."""

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


@dataclass(slots=True)
class ResultTraceEvent:
    """Single trace event produced while a recoverable operation runs."""

    source: str
    status: ResultStatus
    message: str
    details: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ResultError:
    """Structured recoverable error returned by an operation result."""

    code: str
    message: str
    source: str
    details: dict[str, str] = field(default_factory=dict)


SuccessValue = TypeVar("SuccessValue")
FailureValue = TypeVar("FailureValue")


class Result(Generic[SuccessValue, FailureValue]):
    """Represent either a successful value or a recoverable failure.

    This class is intentionally small. BPFW uses it at process boundaries where
    an expected failure should be visible to the caller without turning the main
    orchestration flow into nested ``try``/``except`` blocks.
    """

    def __init__(
        self,
        *,
        success: bool,
        value: SuccessValue | None = None,
        error: FailureValue | None = None,
        trace_events: list[ResultTraceEvent] | None = None,
    ) -> None:
        """Initialize a result container.

        Args:
            success: Whether this result contains a successful value.
            value: Successful value when ``success`` is true.
            error: Failure value when ``success`` is false.
            trace_events: Ordered trace events produced by the operation.
        """
        self._success = success
        self._value = value
        self._error = error
        self.trace_events = trace_events if trace_events is not None else []

    @classmethod
    def ok(
        cls,
        value: SuccessValue,
        trace_events: list[ResultTraceEvent] | None = None,
    ) -> "Result[SuccessValue, FailureValue]":
        """Create a successful result.

        Args:
            value: Successful value to carry.
            trace_events: Ordered trace events produced by the operation.

        Returns:
            Successful result containing ``value``.
        """
        return cls(success=True, value=value, trace_events=trace_events)

    @classmethod
    def fail(
        cls,
        error: FailureValue,
        trace_events: list[ResultTraceEvent] | None = None,
    ) -> "Result[SuccessValue, FailureValue]":
        """Create a failed result.

        Args:
            error: Recoverable failure value to carry.
            trace_events: Ordered trace events produced by the operation.

        Returns:
            Failed result containing ``error``.
        """
        return cls(success=False, error=error, trace_events=trace_events)

    @property
    def is_ok(self) -> bool:
        """Return whether this result represents success."""
        return self._success

    @property
    def is_error(self) -> bool:
        """Return whether this result represents failure."""
        return not self._success

    def unwrap(self) -> SuccessValue:
        """Return the successful value or raise when the result failed.

        Returns:
            Successful value carried by this result.

        Raises:
            RuntimeError: If called on a failed result.
        """
        if not self._success:
            raise RuntimeError("Cannot unwrap a failed Result.")
        return self._value  # type: ignore[return-value]

    def unwrap_error(self) -> FailureValue:
        """Return the failure value or raise when the result succeeded.

        Returns:
            Failure value carried by this result.

        Raises:
            RuntimeError: If called on a successful result.
        """
        if self._success:
            raise RuntimeError("Cannot unwrap_error on a successful Result.")
        return self._error  # type: ignore[return-value]


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
