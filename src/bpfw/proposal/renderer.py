"""Human-readable rendering for proposal commands."""

from __future__ import annotations

from bpfw.proposal.models import Proposal



def render_proposal_list(proposals: list[Proposal]) -> str:
    """Render proposal list for CLI output."""

    if not proposals:
        return "No proposals found"

    lines = []
    for proposal in proposals:
        lines.append(
            (
                f"- {proposal.proposal_id} status={proposal.status} risk={proposal.risk} "
                f"action={proposal.suggested_action} files={len(proposal.detected_files)}"
            )
        )
    return "\n".join(lines)



def render_proposal_detail(proposal: Proposal) -> str:
    """Render one proposal with relevant data."""

    files_text = ", ".join(proposal.detected_files) if proposal.detected_files else "(none)"
    symbols_text = ", ".join(proposal.detected_symbols) if proposal.detected_symbols else "(none)"
    reasons_text = "; ".join(proposal.reason) if proposal.reason else "(none)"

    lines = [
        f"Proposal: {proposal.proposal_id}",
        f"Status: {proposal.status}",
        f"Risk: {proposal.risk}",
        f"Suggested Responsibility: {proposal.suggested_responsibility or '(none)'}",
        f"Suggested Action: {proposal.suggested_action}",
        f"Files: {files_text}",
        f"Symbols: {symbols_text}",
        f"Reasons: {reasons_text}",
    ]

    if proposal.findings:
        lines.append("Findings:")
        for finding in proposal.findings:
            symbol_suffix = f" symbol={finding.symbol_name}" if finding.symbol_name else ""
            lines.append(
                (
                    f"- [{finding.severity}/{finding.risk}] {finding.category}: "
                    f"{finding.file_path}{symbol_suffix}"
                )
            )

    if proposal.resolution:
        resolution_chunks = [f"{key}={value}" for key, value in sorted(proposal.resolution.items())]
        lines.append("Resolution: " + ", ".join(resolution_chunks))

    return "\n".join(lines)
