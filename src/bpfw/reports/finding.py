"""Finding model shared by legacy and system-level BPFW verification."""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

FINDING_SEVERITY_BLOCK = "block"
FINDING_SEVERITY_WARNING = "warning"
FINDING_SEVERITY_INFO = "info"

@dataclass(frozen=True)
class Finding:
    """Represent a normalized finding produced by BPFW."""
    source: str
    code: str
    severity: str
    message: str
    path: Optional[str] = None
    symbol: Optional[str] = None
    evidence: Dict[str, Any] = field(default_factory=dict)
    category: Optional[str] = None
    affected_components: tuple[str, ...] = ()
    affected_invariants: tuple[str, ...] = ()
    confidence: Optional[str] = None
