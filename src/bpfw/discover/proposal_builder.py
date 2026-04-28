"""Build and store discover proposals from scanner findings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from bpfw.blueprint.validator import validate_blueprint
from bpfw.discover.classifier import ClassifiedFinding
from bpfw.discover.risk import aggregate_risk, risk_for_finding
from bpfw.proposal.models import (
    PROPOSAL_SOURCE_DISCOVER,
    PROPOSAL_STATUS_PENDING,
    SUGGESTED_ACTION_ADD_TO_EXISTING,
    SUGGESTED_ACTION_CREATE_NEW,
    SUGGESTED_ACTION_MARK_EXPERIMENTAL,
    Proposal,
    ProposalFinding,
)
from bpfw.proposal.store import list_proposals, save_proposal


@dataclass(slots=True)
class ProposalBuildResult:
    """Discover output after persisting proposals."""

    created: list[Proposal]



def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "proposal"



def _file_key(file_path: str) -> str:
    return Path(file_path).with_suffix("").name



def _deduplicate_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output



def _suggested_responsibility(project_root: Path, file_path: str) -> str:
    blueprint_result = validate_blueprint(project_root=project_root)
    if not blueprint_result.is_valid or blueprint_result.blueprint is None:
        return ""

    file_tokens = {token.lower() for token in Path(file_path).parts if token}
    best_responsibility = ""
    best_score = -1
    for responsibility in blueprint_result.blueprint.responsibilities:
        score = 0
        score += 2 if responsibility.responsibility_id.lower() in file_path.lower() else 0
        score += 2 if responsibility.canonical_name.lower() in file_path.lower() else 0
        responsibility_tokens = set(responsibility.responsibility_id.lower().split("_"))
        score += len(file_tokens.intersection(responsibility_tokens))
        for declared_file in responsibility.allowed_files:
            declared_tokens = {token.lower() for token in Path(declared_file).parts if token}
            score += len(file_tokens.intersection(declared_tokens))
        if score > best_score:
            best_score = score
            best_responsibility = responsibility.responsibility_id

    return best_responsibility



def _group_findings(classified_findings: list[ClassifiedFinding]) -> dict[str, list[ClassifiedFinding]]:
    groups: dict[str, list[ClassifiedFinding]] = {}
    for classified_finding in classified_findings:
        key = classified_finding.finding.file_path or "global"
        groups.setdefault(key, []).append(classified_finding)
    return groups



def _next_proposal_id(project_root: Path, base_slug: str) -> str:
    existing_ids = {proposal.proposal_id for proposal in list_proposals(project_root=project_root)}
    if f"proposal-{base_slug}" not in existing_ids:
        return f"proposal-{base_slug}"

    sequence = 2
    while True:
        candidate = f"proposal-{base_slug}-{sequence}"
        if candidate not in existing_ids:
            return candidate
        sequence += 1



def build_proposals(project_root: Path, classified_findings: list[ClassifiedFinding]) -> ProposalBuildResult:
    """Group findings and persist pending proposals."""

    grouped_findings = _group_findings(classified_findings=classified_findings)
    existing_proposals = list_proposals(project_root=project_root)
    created: list[Proposal] = []

    for file_key, group_findings in sorted(grouped_findings.items()):
        grouped_risks = [risk_for_finding(classified_finding=item) for item in group_findings]
        proposal_risk = aggregate_risk(grouped_risks)

        detected_files = _deduplicate_preserve_order([item.finding.file_path for item in group_findings if item.finding.file_path])
        detected_symbols = _deduplicate_preserve_order(
            [item.finding.symbol_name for item in group_findings if item.finding.symbol_name]
        )
        suggested_responsibility = ""
        if detected_files:
            suggested_responsibility = _suggested_responsibility(project_root=project_root, file_path=detected_files[0])

        reason = _deduplicate_preserve_order([item.finding.message for item in group_findings])
        suggested_action = SUGGESTED_ACTION_CREATE_NEW
        if suggested_responsibility:
            suggested_action = SUGGESTED_ACTION_ADD_TO_EXISTING
        if proposal_risk in {"high", "critical"}:
            suggested_action = SUGGESTED_ACTION_MARK_EXPERIMENTAL

        proposal_findings = [
            ProposalFinding(
                category=item.category,
                severity=item.severity,
                risk=risk_for_finding(classified_finding=item),
                message=item.finding.message,
                file_path=item.finding.file_path,
                symbol_name=item.finding.symbol_name,
                symbol_type=item.finding.symbol_type,
                line_number=item.finding.line_number,
                code=item.finding.code,
                recommendation=item.finding.recommendation,
            )
            for item in group_findings
        ]

        duplicate_exists = any(
            proposal.status == PROPOSAL_STATUS_PENDING
            and proposal.detected_files == detected_files
            and proposal.detected_symbols == detected_symbols
            for proposal in existing_proposals
        )
        if duplicate_exists:
            continue

        proposal_id = _next_proposal_id(project_root=project_root, base_slug=_slugify(_file_key(file_key)))
        proposal = Proposal(
            proposal_id=proposal_id,
            source=PROPOSAL_SOURCE_DISCOVER,
            status=PROPOSAL_STATUS_PENDING,
            detected_files=detected_files,
            detected_symbols=detected_symbols,
            suggested_responsibility=suggested_responsibility,
            suggested_action=suggested_action,
            risk=proposal_risk,
            reason=reason,
            options=[
                "reject",
                SUGGESTED_ACTION_ADD_TO_EXISTING,
                SUGGESTED_ACTION_CREATE_NEW,
                SUGGESTED_ACTION_MARK_EXPERIMENTAL,
            ],
            findings=proposal_findings,
        )
        save_proposal(project_root=project_root, proposal=proposal)
        created.append(proposal)
        existing_proposals.append(proposal)

    return ProposalBuildResult(created=created)
