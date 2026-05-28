"""PURPOSE data models for BPFW catalog mode
DOMAIN  blueprint checks
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from bpfw.reports.finding import Finding

# Authority state constants
AUTHORITY_STATE_MISSING = "missing"
AUTHORITY_STATE_EMPTY = "empty"
AUTHORITY_STATE_DRAFT = "draft"
AUTHORITY_STATE_DEFINED = "defined"
AUTHORITY_STATE_INVALID = "invalid"


@dataclass(frozen=True)
class DiscoveredCodeUnit:
    """PURPOSE store information about a code unit discovered by Python code tree scanning
        DOMAIN  blueprint checks

    """

    path: str
    module: str
    symbol: str
    symbol_type: str
    qualified_name: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    methods: List[str] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    decorators: List[str] = field(default_factory=list)
    docstring: Optional[str] = None
    signature: Optional[str] = None
    interface_inputs: List[Dict[str, Any]] = field(default_factory=list)
    interface_output: Optional[Dict[str, Any]] = None
    calls: List[Dict[str, Any]] = field(default_factory=list)
    """Structured call references extracted from AST. Each dict has 'context' and 'name' keys."""
    normalized_body_hash: Optional[str] = None
    dangerous_capabilities: Dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class BlueprintLoadResult:
    """PURPOSE result of loading and parsing blueprint.yaml
    DOMAIN  blueprint checks
    """

    state: str
    path: str
    data: Dict[str, Any]
    domain_document: Any | None = None
    authority_document: Any | None = None
    findings: List[Finding] = field(default_factory=list)


@dataclass(frozen=True)
class ScanResult:
    """PURPOSE result of scanning Python code with Python code tree
        DOMAIN  blueprint checks

    """

    discovered_units: List[DiscoveredCodeUnit]
    findings: List[Finding] = field(default_factory=list)


@dataclass(frozen=True)
class VerificationReport:
    """PURPOSE report from verifying blueprint against discovered code
    DOMAIN  blueprint checks
    """

    authority_state: str
    allowed: bool
    findings: List[Finding]
    declared_count: int = 0
    discovered_count: int = 0
    missing_declared_count: int = 0
    undeclared_count: int = 0
    duplicate_active_purpose_count: int = 0
    invalid_lifecycle_count: int = 0
    incomplete_responsibility_count: int = 0
