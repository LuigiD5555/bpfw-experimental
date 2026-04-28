"""Deterministic persistence for discover proposals."""

from __future__ import annotations

from pathlib import Path

from bpfw.change.store import ChangeStoreError, ensure_directory, read_json, write_json
from bpfw.proposal.models import Proposal, ProposalFinding, utc_now_iso


PROPOSALS_RELATIVE_DIR = ".bpfw/proposals"


class ProposalStoreError(RuntimeError):
    """Raised when proposal storage operations fail."""



def proposal_root(project_root: Path) -> Path:
    """Resolve proposal root directory."""

    return project_root / PROPOSALS_RELATIVE_DIR



def proposal_file_path(project_root: Path, proposal_id: str) -> Path:
    """Build proposal file path."""

    return proposal_root(project_root=project_root) / f"{proposal_id}.json"



def _proposal_from_dict(payload: dict[str, object]) -> Proposal:
    findings_payload = payload.get("findings", [])
    findings: list[ProposalFinding] = []
    if isinstance(findings_payload, list):
        for item in findings_payload:
            if not isinstance(item, dict):
                continue
            findings.append(
                ProposalFinding(
                    category=str(item.get("category", "")),
                    severity=str(item.get("severity", "")),
                    risk=str(item.get("risk", "")),
                    message=str(item.get("message", "")),
                    file_path=str(item.get("file_path", "")),
                    symbol_name=str(item.get("symbol_name", "")),
                    symbol_type=str(item.get("symbol_type", "")),
                    line_number=int(item.get("line_number", 0) or 0),
                    code=str(item.get("code", "")),
                    recommendation=str(item.get("recommendation", "")),
                )
            )

    resolution_value = payload.get("resolution", {})
    if not isinstance(resolution_value, dict):
        resolution_value = {}

    return Proposal(
        proposal_id=str(payload.get("proposal_id", "")),
        source=str(payload.get("source", "discover")),
        status=str(payload.get("status", "pending")),
        detected_files=[str(item) for item in payload.get("detected_files", []) or []],
        detected_symbols=[str(item) for item in payload.get("detected_symbols", []) or []],
        suggested_responsibility=str(payload.get("suggested_responsibility", "")),
        suggested_action=str(payload.get("suggested_action", "")),
        risk=str(payload.get("risk", "medium")),
        reason=[str(item) for item in payload.get("reason", []) or []],
        options=[str(item) for item in payload.get("options", []) or []],
        findings=findings,
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at", "")),
        resolution={str(key): str(value) for key, value in resolution_value.items()},
    )



def save_proposal(project_root: Path, proposal: Proposal) -> Proposal:
    """Persist one proposal."""

    if not proposal.created_at:
        proposal.created_at = utc_now_iso()
    proposal.updated_at = utc_now_iso()

    try:
        write_json(path=proposal_file_path(project_root=project_root, proposal_id=proposal.proposal_id), payload=proposal.to_dict())
    except ChangeStoreError as error:
        raise ProposalStoreError(str(error)) from error

    return proposal



def load_proposal(project_root: Path, proposal_id: str) -> Proposal:
    """Load one proposal by id."""

    try:
        payload = read_json(path=proposal_file_path(project_root=project_root, proposal_id=proposal_id))
    except ChangeStoreError as error:
        raise ProposalStoreError(str(error)) from error

    proposal = _proposal_from_dict(payload)
    if not proposal.proposal_id:
        raise ProposalStoreError(f"Proposal payload missing proposal_id: {proposal_id}")
    return proposal



def list_proposals(project_root: Path) -> list[Proposal]:
    """List all proposals sorted by id."""

    root = proposal_root(project_root=project_root)
    if not root.exists():
        return []

    proposals: list[Proposal] = []
    for file_path in sorted(root.glob("*.json")):
        try:
            payload = read_json(path=file_path)
        except ChangeStoreError:
            continue
        proposal = _proposal_from_dict(payload)
        if proposal.proposal_id:
            proposals.append(proposal)
    return proposals



def ensure_proposal_root(project_root: Path) -> Path:
    """Ensure proposal directory exists."""

    root = proposal_root(project_root=project_root)
    ensure_directory(root)
    return root
