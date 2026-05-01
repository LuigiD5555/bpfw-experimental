"""Result objects for dormant external tool integrations."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ExternalToolFinding:
    """Represent a finding produced by an external tool adapter."""

    tool: str
    code: str
    severity: str
    message: str
    path: Optional[str] = None
    line: Optional[int] = None
    symbol: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)
