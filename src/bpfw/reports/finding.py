"""Finding model for BPFW catalog mode."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# Severity constants
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