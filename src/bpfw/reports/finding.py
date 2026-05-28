"""PURPOSE finding model for BPFW catalog mode
DOMAIN  terminal reports
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# Severity constants
FINDING_SEVERITY_BLOCK = "block"
FINDING_SEVERITY_WARNING = "warning"
FINDING_SEVERITY_INFO = "info"


@dataclass(frozen=True)
class Finding:
    """PURPOSE store information about a clean finding produced by BPFW
    DOMAIN  terminal reports
    """

    source: str
    code: str
    severity: str
    message: str
    path: Optional[str] = None
    symbol: Optional[str] = None
    evidence: Dict[str, Any] = field(default_factory=dict)