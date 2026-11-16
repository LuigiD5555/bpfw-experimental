"""Context provided to system-level analyzers."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bpfw.core.catalog.domain.models import BlueprintDocument
from bpfw.core.catalog.models import ScanResult
from bpfw.core.graph.models import SystemGraph

@dataclass
class VerificationContext:
    project_root: Path
    blueprint: BlueprintDocument
    raw_blueprint: dict[str, Any]
    graph: SystemGraph
    scan_result: ScanResult | None = None
    diff_paths: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)
    proposed_changes: tuple[dict[str, Any], ...] = ()
