"""Report structures for composition root verification."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class CompositionIssue:
    """Single composition check issue."""

    severity: str
    code: str
    message: str
    file_path: str
    recommendation: str


@dataclass(slots=True)
class CompositionReport:
    """Aggregated composition verification result."""

    is_valid: bool
    errors: list[CompositionIssue] = field(default_factory=list)
    warnings: list[CompositionIssue] = field(default_factory=list)
