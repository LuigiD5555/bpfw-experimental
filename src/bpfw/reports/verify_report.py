"""Verify report rendering for BPFW MVP Catalog Mode."""

from collections import defaultdict
from typing import DefaultDict, Dict, List, Sequence

from bpfw.catalog.status import ALLOWED_STATUSES
from bpfw.catalog.models import VerificationReport
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
        "Sync bpfw/blueprint.yaml by completing: id, purpose, name, domain, status, "
        "code.path, code.symbol, and code.kind."
    ),
    "INVALID_STATUS": (
        f"Use {', '.join(ALLOWED_STATUSES)}."
    ),
    "DUPLICATE_BLOCK_ID": (
        "Give every block a unique id."
    ),
    "DUPLICATE_ACTIVE_PURPOSE": (
        "Keep one block active and mark the others "
        "experimental, legacy, or deprecated."
    ),
    "MISSING_DECLARED_CODE": (
        "Restore the declared code unit or update the blueprint "
        "code location intentionally."
    ),
    "UNDECLARED_CODE": (
        "Add it to the blueprint with status experimental, "
        "legacy, deprecated, or active. If it duplicates an "
        "existing purpose, do not mark both as active."
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
    "duplicate": {"DUPLICATE_ACTIVE_PURPOSE", "DUPLICATE_BLOCK_ID"},
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


def _render_block_group(code: str, grouped_findings: List[Finding], max_items: int = 8) -> str:
    """Render one grouped finding code with compact locations."""
    lines: List[str] = []
    lines.append(f"[{code}] count={len(grouped_findings)}")

    first_finding = grouped_findings[0]
    lines.append(f"Reason: {first_finding.message}")
    action = _SUGGESTED_ACTIONS.get(code, "Review and resolve the finding.")
    lines.append(f"Suggested action: {action}")

    unique_locations: List[str] = []
    seen_locations = set()
    for finding in grouped_findings:
        location = _compact_location(finding)
        if location in seen_locations:
            continue
        seen_locations.add(location)
        unique_locations.append(location)

    lines.append("Locations:")
    if max_items <= 0:
        max_items = len(unique_locations)

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

    if report.allowed:
        # Authority summary for passed reports
        sections.append("Authority:")
        sections.append("  mode: catalog")
        sections.append(f"  state: {report.authority_state}")
        sections.append("")

        # Code alignment
        sections.append("Code alignment:")
        sections.append(f"  declared blocks: {report.declared_count}")
        sections.append(f"  discovered code units: {report.discovered_count}")
        sections.append(f"  missing declared code: {report.missing_declared_count}")
        sections.append(f"  undeclared code: {report.undeclared_count}")
        sections.append("")

        # Lifecycle
        sections.append("Lifecycle:")
        sections.append(f"  invalid lifecycles: {report.invalid_lifecycle_count}")
        sections.append(f"  duplicate active purposes: {report.duplicate_active_purpose_count}")
        sections.append("")

        # Execution
        sections.append("Execution:")
        sections.append("  ALLOWED")
    else:
        filtered_findings = _filter_block_findings(block_findings, finding_codes)
        grouped_findings = _group_block_findings(filtered_findings)

        if finding_codes:
            sections.append(f"Filter: {', '.join(finding_codes)}")
            sections.append("")

        if not grouped_findings:
            sections.append("Findings summary:")
            sections.append("  No findings match the selected filter.")
            sections.append("")
            sections.append(f"Hidden findings: {len(block_findings)}")
            sections.append("")
        else:
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

        sections.append("Execution:")
        sections.append("  BLOCKED")

    return "\n".join(sections)
