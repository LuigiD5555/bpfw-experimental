"""Verify report rendering for BPFW MVP Catalog Mode."""

from typing import Dict, List

from bpfw.catalog.lifecycle import ALLOWED_LIFECYCLES
from bpfw.catalog.models import VerificationReport
from bpfw.reports.finding import FINDING_SEVERITY_BLOCK, Finding

# Suggested actions keyed by finding code.
_SUGGESTED_ACTIONS: Dict[str, str] = {
    "NO_AUTHORITY": (
        "Run bpfw init when you are ready to create project authority."
    ),
    "EMPTY_AUTHORITY": (
        "Add responsibilities with bpfw init or bpfw wizard "
        "when you are ready to enforce authority."
    ),
    "INVALID_BLUEPRINT": (
        "Fix bpfw/blueprint.yaml so it can be parsed and loaded."
    ),
    "INCOMPLETE_RESPONSIBILITY": (
        "Complete intent, canonical_name, owner_layer, lifecycle, "
        "location.path, location.symbol, and location.symbol_type."
    ),
    "INVALID_LIFECYCLE": (
        f"Use {', '.join(ALLOWED_LIFECYCLES)}."
    ),
    "DUPLICATE_RESPONSIBILITY_ID": (
        "Give every responsibility a unique id."
    ),
    "DUPLICATE_ACTIVE_INTENT": (
        "Keep one responsibility active and mark the others "
        "experimental, legacy, or deprecated."
    ),
    "MISSING_DECLARED_CODE": (
        "Restore the declared code unit or update the blueprint "
        "location intentionally."
    ),
    "UNDECLARED_CODE": (
        "Add it to the blueprint with lifecycle experimental, "
        "legacy, deprecated, or active. If it duplicates an "
        "existing intent, do not mark both as active."
    ),
    "PYTHON_PARSE_ERROR": (
        "Fix the Python syntax error before running verification again."
    ),
    "BLUEPRINT_LOCKED": (
        "Run bpfw unlock before editing."
    ),
}


def _render_block_finding(finding: Finding) -> str:
    """Render a single block finding as human-readable text."""
    lines: List[str] = []

    lines.append(f"[{finding.code}]")
    lines.append("Path:")
    lines.append(f"  {finding.path or 'n/a'}")
    lines.append("")
    lines.append("Symbol:")
    lines.append(f"  {finding.symbol or 'n/a'}")
    lines.append("")
    lines.append("Reason:")
    lines.append(f"  {finding.message}")
    lines.append("")
    lines.append("Suggested action:")
    action = _SUGGESTED_ACTIONS.get(finding.code, "Review and resolve the finding.")
    lines.append(f"  {action}")

    return "\n".join(lines)


def render_verify_report(report: VerificationReport) -> str:
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
        sections.append(f"  declared responsibilities: {report.declared_count}")
        sections.append(f"  discovered code units: {report.discovered_count}")
        sections.append(f"  missing declared code: {report.missing_declared_count}")
        sections.append(f"  undeclared code: {report.undeclared_count}")
        sections.append("")

        # Lifecycle
        sections.append("Lifecycle:")
        sections.append(f"  invalid lifecycles: {report.invalid_lifecycle_count}")
        sections.append(f"  duplicate active intents: {report.duplicate_active_intent_count}")
        sections.append("")

        # Execution
        sections.append("Execution:")
        sections.append("  ALLOWED")
    else:
        # Blocked: render each block finding, then execution
        for finding in block_findings:
            sections.append(_render_block_finding(finding))
            sections.append("")

        sections.append("Execution:")
        sections.append("  BLOCKED")

    return "\n".join(sections)
