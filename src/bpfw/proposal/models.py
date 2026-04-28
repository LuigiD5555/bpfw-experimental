"""Domain models for discover proposals."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


PROPOSAL_SOURCE_DISCOVER = "discover"
PROPOSAL_STATUS_PENDING = "pending"
PROPOSAL_STATUS_ACCEPTED = "accepted"
PROPOSAL_STATUS_REJECTED = "rejected"

SUGGESTED_ACTION_ADD_TO_EXISTING = "add_to_existing_responsibility"
SUGGESTED_ACTION_CREATE_NEW = "create_new_responsibility"
SUGGESTED_ACTION_MARK_EXPERIMENTAL = "mark_experimental"

REJECT_ACTION_MOVE = "move_to_rejected"
REJECT_ACTION_UNTRACKED = "leave_untracked"
REJECT_ACTION_SUGGEST_DELETE = "suggest_delete"


@dataclass(slots=True)
class ProposalFinding:
    """One discover finding attached to a proposal."""

    category: str
    severity: str
    risk: str
    message: str
    file_path: str
    symbol_name: str = ""
    symbol_type: str = ""
    line_number: int = 0
    code: str = ""
    recommendation: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "severity": self.severity,
            "risk": self.risk,
            "message": self.message,
            "file_path": self.file_path,
            "symbol_name": self.symbol_name,
            "symbol_type": self.symbol_type,
            "line_number": self.line_number,
            "code": self.code,
            "recommendation": self.recommendation,
        }


@dataclass(slots=True)
class Proposal:
    """Proposal persisted under .bpfw/proposals."""

    proposal_id: str
    source: str
    status: str
    detected_files: list[str]
    detected_symbols: list[str]
    suggested_responsibility: str
    suggested_action: str
    risk: str
    reason: list[str]
    options: list[str]
    findings: list[ProposalFinding] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    resolution: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "source": self.source,
            "status": self.status,
            "detected_files": self.detected_files,
            "detected_symbols": self.detected_symbols,
            "suggested_responsibility": self.suggested_responsibility,
            "suggested_action": self.suggested_action,
            "risk": self.risk,
            "reason": self.reason,
            "options": self.options,
            "findings": [finding.to_dict() for finding in self.findings],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "resolution": self.resolution,
        }



def utc_now_iso() -> str:
    """Return deterministic UTC timestamp without microseconds."""

    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
