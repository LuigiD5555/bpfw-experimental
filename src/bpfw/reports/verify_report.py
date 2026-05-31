"""Verify report rendering for BPFW catalog mode."""

from collections import defaultdict
from typing import DefaultDict, Dict, List, Sequence

from bpfw.core.catalog.status import ALLOWED_STATUSES
from bpfw.core.catalog.models import VerificationReport
from bpfw.reports.finding import FINDING_SEVERITY_BLOCK, Finding

# Suggested actions keyed by finding code.
_SUGGESTED_ACTIONS: Dict[str, str] = {
    "NO_AUTHORITY": (
        "Run bpfw init when you are ready to create project authority."
    ),
    "EMPTY_AUTHORITY": (
        "Add blocks with bpfw planner or bpfw inspector "
        "when you are ready to enforce authority."
    ),
    "INVALID_BLUEPRINT": (
        "Fix bpfw/blueprint.yaml so it can be parsed and loaded."
    ),
    "INCOMPLETE_BLOCK": (
        "Sync bpfw/blueprint.yaml by completing: id, domain, status, "
        "code.path, code.symbol, and code.kind."
    ),
    "INVALID_STATUS": (
        f"Use {', '.join(ALLOWED_STATUSES)}."
    ),
    "DUPLICATE_BLOCK_ID": (
        "Give every block a unique id."
    ),
    "DUPLICATE_ACTIVE_PROFILE": (
        "Keep one active implementation, mark the competing blocks experimental, "
        "legacy, or deprecated, or explicitly allow this duplicate profile when "
        "it is a confirmed false positive."
    ),
    "DUPLICATE_PROFILE_REVIEW": (
        "Review whether these similar active blocks are intentionally separate. "
        "This is a warning only and does not block execution."
    ),
    "NORMALIZED_AST_CLONE": (
        "Review whether these blocks should share one implementation or stay separate."
    ),
    "SAME_RETURN_EXPRESSION": (
        "Review whether the repeated return behavior is intentional."
    ),
    "TRIVIAL_WRAPPER": (
        "Remove the wrapper or justify the policy, entrypoint, or compatibility boundary."
    ),
    "SAME_OUTCOME": (
        "Review whether these blocks should share one implementation or stay separate by layer."
    ),
    "SIMILAR_OUTCOME": (
        "Review whether these blocks serve the same observable purpose."
    ),
    "CONFLICTING_EFFECT": (
        "Review whether these blocks intentionally apply opposite actions to the same resource."
    ),
    "UNCLASSIFIED_EXTERNAL_EFFECT": (
        "Classify the external call, declare the effect, or add a domain analyzer."
    ),
    "MISSING_DECLARED_CODE": (
        "Restore the declared code unit or update the blueprint "
        "code location intentionally."
    ),
    "UNDECLARED_CODE": (
        "Add it to the blueprint with status experimental, "
        "legacy, deprecated, or active. If it duplicates an existing "
        "calculated duplicate profile, do not mark both as active."
    ),
    "PYTHON_PARSE_ERROR": (
        "Fix the Python syntax error before running verification again."
    ),
    "BLUEPRINT_LOCKED": (
        "Run bpfw unlock before editing."
    ),
}

VERIFY_FINDING_FILTERS: Dict[str, set[str]] = {
    "all": set(),
    "undeclared": {"UNDECLARED_CODE"},
    "missing": {"MISSING_DECLARED_CODE"},
    "duplicate": {
        "DUPLICATE_ACTIVE_PROFILE",
        "DUPLICATE_PROFILE_REVIEW",
        "DUPLICATE_BLOCK_ID",
        "NORMALIZED_AST_CLONE",
        "SAME_RETURN_EXPRESSION",
        "TRIVIAL_WRAPPER",
        "SAME_OUTCOME",
        "SIMILAR_OUTCOME",
        "CONFLICTING_EFFECT",
    },
    "clone": {"NORMALIZED_AST_CLONE", "SAME_RETURN_EXPRESSION"},
    "wrapper": {"TRIVIAL_WRAPPER"},
    "effect": {"SAME_OUTCOME", "SIMILAR_OUTCOME", "CONFLICTING_EFFECT", "UNCLASSIFIED_EXTERNAL_EFFECT"},
    "outcome": {"SAME_OUTCOME", "SIMILAR_OUTCOME", "CONFLICTING_EFFECT"},
    "secret": {"BLUEPRINT_SECRET_LIKE_VALUE"},
    "invalid": {"INVALID_STATUS", "INCOMPLETE_BLOCK", "INVALID_BLUEPRINT"},
}


def _group_block_findings(findings: List[Finding]) -> DefaultDict[str, List[Finding]]:
    """Group findings by code while preserving input order inside each group."""
    grouped: DefaultDict[str, List[Finding]] = defaultdict(list)
    for finding in findings:
        grouped[finding.code].append(finding)
    return grouped


def _compact_location(finding: Finding) -> str:
    """Return a compact and stable location string."""
    path_value = finding.path or "n/a"
    symbol_value = finding.symbol or "n/a"
    return f"{path_value}::{symbol_value}"


def _render_evidence(finding: Finding) -> List[str]:
    """Render compact evidence lines for one finding."""
    evidence = finding.evidence or {}
    lines: List[str] = []
    if "purpose" in evidence:
        lines.append(f"Purpose: {evidence.get('purpose')}")
    if "active_block_ids" in evidence:
        lines.append("Active blocks:")
        for block_id in evidence.get("active_block_ids", [])[:8]:
            lines.append(f"  - {block_id}")
    if "duplicate_key" in evidence:
        lines.append(f"Duplicate key: {evidence.get('duplicate_key')}")
    if "duplicate_hash" in evidence:
        lines.append(f"Duplicate hash: {evidence.get('duplicate_hash')}")
    if "hash_strength" in evidence:
        lines.append(f"Hash strength: {evidence.get('hash_strength')}")
    if "reason" in evidence:
        lines.append(f"Reason: {evidence.get('reason')}")
    if "active_blocks" in evidence:
        lines.append("Active blocks:")
        for active_block in evidence.get("active_blocks", [])[:8]:
            if isinstance(active_block, dict):
                block_id = active_block.get("id", "unknown")
                path = active_block.get("path", "n/a")
                symbol = active_block.get("symbol", "n/a")
                purpose = active_block.get("purpose")
                lines.append(f"  - {block_id}: {path}::{symbol}")
                if purpose:
                    lines.append(f"    purpose: {purpose}")
            else:
                lines.append(f"  - {active_block}")
    if "units" in evidence:
        lines.append("Units:")
        for unit_label in evidence.get("units", [])[:8]:
            lines.append(f"  - {unit_label}")
    if "target" in evidence:
        lines.append(f"Target: {evidence.get('target')}")
    if "passed_arguments" in evidence:
        arguments = ", ".join(str(argument) for argument in evidence.get("passed_arguments", []))
        lines.append(f"Passed arguments: {arguments}")
    if "calls" in evidence and evidence.get("calls"):
        calls = ", ".join(str(call) for call in evidence.get("calls", [])[:8])
        lines.append(f"Calls: {calls}")
    if "shared_calls" in evidence and evidence.get("shared_calls"):
        shared_calls = ", ".join(str(call) for call in evidence.get("shared_calls", [])[:8])
        lines.append(f"Shared calls: {shared_calls}")
    if "action" in evidence:
        lines.append(f"Action: {evidence.get('action')}")
    if "resource_kind" in evidence:
        lines.append(f"Resource: {evidence.get('resource_kind')}")
    if "target" in evidence and evidence.get("target") is not None:
        lines.append(f"Target: {evidence.get('target')}")
    if "confidence" in evidence:
        lines.append(f"Confidence: {evidence.get('confidence')}")
    if "effects" in evidence and evidence.get("effects"):
        lines.append("Effects:")
        for effect in evidence.get("effects", [])[:8]:
            lines.append(f"  - {effect}")
    return lines


def _render_block_group(code: str, grouped_findings: List[Finding], max_items: int = 8) -> str:
    """Render one grouped finding code with compact evidence."""
    lines: List[str] = []
    lines.append(f"[{code}] count={len(grouped_findings)}")

    first_finding = grouped_findings[0]
    lines.append(f"Severity: {first_finding.severity}")
    lines.append(f"Reason: {first_finding.message}")
    action = _SUGGESTED_ACTIONS.get(code, "Review and resolve the finding.")
    lines.append(f"Suggested action: {action}")

    if max_items <= 0:
        max_items = len(grouped_findings)

    if code in {
        "NORMALIZED_AST_CLONE",
        "SAME_RETURN_EXPRESSION",
        "TRIVIAL_WRAPPER",
        "SAME_OUTCOME",
        "SIMILAR_OUTCOME",
        "CONFLICTING_EFFECT",
        "UNCLASSIFIED_EXTERNAL_EFFECT",
        "DUPLICATE_ACTIVE_PROFILE",
        "DUPLICATE_PROFILE_REVIEW",
    }:
        lines.append("Items:")
        for index, finding in enumerate(grouped_findings[:max_items], start=1):
            lines.append(f"  {index}. {_compact_location(finding)}")
            evidence_lines = _render_evidence(finding)
            for evidence_line in evidence_lines:
                lines.append(f"     {evidence_line}")
        remaining_items = len(grouped_findings) - max_items
        if remaining_items > 0:
            lines.append(f"  ... and {remaining_items} more")
        return "\n".join(lines)

    unique_locations: List[str] = []
    seen_locations = set()
    for finding in grouped_findings:
        location = _compact_location(finding)
        if location in seen_locations:
            continue
        seen_locations.add(location)
        unique_locations.append(location)

    evidence_lines = _render_evidence(first_finding)
    if evidence_lines:
        lines.append("Evidence:")
        lines.extend(f"  {line}" for line in evidence_lines)

    lines.append("Locations:")
    for location in unique_locations[:max_items]:
        lines.append(f"  - {location}")

    remaining = len(unique_locations) - max_items
    if remaining > 0:
        lines.append(f"  ... and {remaining} more")

    return "\n".join(lines)


def _filter_block_findings(
    block_findings: List[Finding],
    finding_codes: Sequence[str] | None,
) -> List[Finding]:
    """Filter findings by a list of explicit finding codes."""
    if not finding_codes:
        return block_findings
    allowed_codes = set(finding_codes)
    return [finding for finding in block_findings if finding.code in allowed_codes]


def render_verify_report(
    report: VerificationReport,
    finding_codes: Sequence[str] | None = None,
    max_items_per_group: int = 8,
) -> str:
    """Render a VerificationReport into a human-readable string.

    Parameters
    ----------
    report:
        The verification report to render.

    Returns
    -------
    str
        Formatted multi-line report ready for terminal output.
    """
    sections: List[str] = []

    # Header
    if report.allowed:
        sections.append("BPFW VERIFY PASSED")
    else:
        sections.append("BPFW VERIFY BLOCKED")

    sections.append("")

    # Block findings detail (shown before execution for blocked reports)
    block_findings = [
        finding for finding in report.findings
        if finding.severity == FINDING_SEVERITY_BLOCK
    ]

    findings_for_filter = report.findings if finding_codes else block_findings
    filtered_findings = _filter_block_findings(findings_for_filter, finding_codes)
    grouped_findings = _group_block_findings(filtered_findings)

    if finding_codes:
        sections.append(f"Filter: {', '.join(finding_codes)}")
        sections.append("")

    if grouped_findings:
        sections.append("Findings summary:")
        for finding_code in sorted(grouped_findings):
            sections.append(f"  {finding_code}: {len(grouped_findings[finding_code])}")
        sections.append("")

        sections.append("Findings detail:")
        for finding_code in sorted(grouped_findings):
            sections.append(
                _render_block_group(
                    finding_code,
                    grouped_findings[finding_code],
                    max_items=max_items_per_group,
                )
            )
            sections.append("")
    elif not report.allowed and finding_codes:
        sections.append("Findings summary:")
        sections.append("  No findings match the selected filter.")
        sections.append("")
        sections.append(f"Hidden findings: {len(block_findings)}")
        sections.append("")

    if report.allowed:
        sections.append("Authority:")
        sections.append("  mode: catalog")
        sections.append(f"  state: {report.authority_state}")
        sections.append("")

        sections.append("Code alignment:")
        sections.append(f"  declared blocks: {report.declared_count}")
        sections.append(f"  discovered code units: {report.discovered_count}")
        sections.append(f"  missing declared code: {report.missing_declared_count}")
        sections.append(f"  undeclared code: {report.undeclared_count}")
        sections.append("")

        sections.append("Lifecycle:")
        sections.append(f"  invalid lifecycles: {report.invalid_lifecycle_count}")
        sections.append(f"  duplicate active profiles: {report.duplicate_active_profile_count}")
        sections.append(f"  duplicate review warnings: {report.duplicate_profile_review_count}")
        sections.append("")

        sections.append("Execution:")
        sections.append("  ALLOWED")
    else:
        sections.append("Execution:")
        sections.append("  BLOCKED")

    return "\n".join(sections)
