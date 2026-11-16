"""Parser-neutral artifact resolution models."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ResolvedArtifact:
    artifact_id: str
    artifact_uid: str | None
    type: str
    path: str
    language: str | None = None
    format: str | None = None
    symbol: str | None = None
    kind: str | None = None
    role: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    start_column: int | None = None
    end_column: int | None = None
    start_byte: int | None = None
    end_byte: int | None = None
    content_hash: str | None = None
    structural_hash: str | None = None
    resolution: str = "UNRESOLVED"
    parser: str = "none"
    confidence: str = "low"
    detected: dict[str, Any] = field(default_factory=dict)
    message: str | None = None

    @property
    def resolved(self) -> bool:
        return self.start_line is not None and self.end_line is not None and self.resolution != "UNRESOLVED"
