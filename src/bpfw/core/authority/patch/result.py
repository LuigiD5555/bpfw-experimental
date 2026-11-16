"""Structured result of applying an authority patch plan."""

from dataclasses import dataclass, field
from pathlib import Path

from bpfw.core.result import ResultStatus, ResultTraceEvent


@dataclass
class AuthorityPatchResult:
    """Structured result returned by ``AuthorityPatchEngine.apply``.

    Attributes:
        success: Whether all operations were applied without errors.
        applied_operations: Operation kinds that were successfully applied.
        skipped_operations: Operation kinds that were skipped due to
            precondition failures.
        modified_files: Project-relative paths that were written.
        manifest_updated: Whether the root index was updated.
        rolled_back: Whether a rollback was attempted after a failure.
        messages: Human-readable informational messages.
        error_message: Optional error description when success is False.
        trace_events: Ordered internal process events for debugging and audit.
    """

    success: bool = False
    applied_operations: list[str] = field(default_factory=list)
    skipped_operations: list[str] = field(default_factory=list)
    modified_files: list[Path] = field(default_factory=list)
    manifest_updated: bool = False
    rolled_back: bool = False
    messages: list[str] = field(default_factory=list)
    error_message: str | None = None
    trace_events: list[ResultTraceEvent] = field(default_factory=list)

    def add_applied(self, kind_label: str) -> None:
        """Record a successfully applied operation.

        Args:
            kind_label: The ``PatchOperationKind.value`` string.
        """
        self.applied_operations.append(kind_label)

    def add_skipped(self, kind_label: str, reason: str) -> None:
        """Record a skipped operation.

        Args:
            kind_label: The ``PatchOperationKind.value`` string.
            reason: Why the operation was skipped.
        """
        self.skipped_operations.append(kind_label)
        self.messages.append(f"Skipped {kind_label}: {reason}")

    def add_modified(self, path: Path) -> None:
        """Record a file that was written.

        Args:
            path: Project-relative path of the modified file.
        """
        self.modified_files.append(path)

    def add_trace(
        self,
        source: str,
        status: ResultStatus,
        message: str,
        details: dict[str, str] | None = None,
    ) -> None:
        """Record one internal process trace event.

        Args:
            source: Internal component or step that produced the trace event.
            status: Normalized result status for the event.
            message: Human-readable event summary.
            details: Optional structured details for diagnostics.
        """
        self.trace_events.append(
            ResultTraceEvent(
                source=source,
                status=status,
                message=message,
                details=details if details is not None else {},
            )
        )

    def extend_trace(self, trace_events: list[ResultTraceEvent]) -> None:
        """Append trace events produced by a nested result.

        Args:
            trace_events: Ordered trace events to append.
        """
        self.trace_events.extend(trace_events)
