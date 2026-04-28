"""Runtime snapshot contracts for active binding detection."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RuntimeBinding:
    """One responsibility binding as observed in runtime metadata."""

    responsibility_id: str
    declared_active_implementation: str
    runtime_implementation: str | None
    source: str


@dataclass(slots=True)
class RuntimeSnapshotDocument:
    """Serializable runtime snapshot document."""

    active_bindings: list[RuntimeBinding] = field(default_factory=list)


@dataclass(slots=True)
class RuntimeCollectionIssue:
    """Runtime collection warning or error."""

    severity: str
    code: str
    message: str
    file_path: str
    recommendation: str


@dataclass(slots=True)
class RuntimeCollectionResult:
    """Collector output for snapshot and verify integration."""

    snapshot: RuntimeSnapshotDocument | None = None
    warnings: list[RuntimeCollectionIssue] = field(default_factory=list)
    errors: list[RuntimeCollectionIssue] = field(default_factory=list)
