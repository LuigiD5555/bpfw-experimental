"""Evidence records produced by deterministic verification runs."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any

@dataclass(frozen=True)
class EvidenceRequirement:
    invariant_id: str
    kind: str
    command: tuple[str, ...] = ()
    scenario: str | None = None

@dataclass
class EvidenceRecord:
    invariant_id: str
    status: str
    fingerprint: str
    timestamp: str
    pipeline: str
    run_id: str | None = None
    scenario: str | None = None
    report_path: str | None = None
    events_path: str | None = None
    stdout: str = ""
    stderr: str = ""
    operation_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
