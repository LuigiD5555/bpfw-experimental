"""Verify report rendering for BPFW MVP Catalog Mode."""

from typing import Dict

from bpfw.catalog.lifecycle import ALLOWED_LIFECYCLES
from bpfw.catalog.models import VerificationReport
from bpfw.reports.finding import FINDING_SEVERITY_BLOCK, Finding

# Suggested actions keyed by finding code.
_SUGGESTED_ACTIONS: Dict[str, str] = {
    "UNDECLARED_CODE": (
        "Add it to bpfw/blueprint.yaml with lifecycle "
        f"{', '.join(ALLOWED_LIFECYCLES)}. If it duplicates an existing intent, do not "
        "mark both as active."
    ),
    "MISSING_DECLARED_CODE": (
        "Restore the declared code unit or update the blueprint location "
        "intentionally."
    ),
    "DUPLICATE_ACTIVE_INTENT": (
        "Keep one responsibility active and mark the others "
        "experimental, legacy, or deprecated."
    ),
    "INVALID_LIFECYCLE": f"Use {', '.join(ALLOWED_LIFECYCLES)}.",
    "INCOMPLETE_RESPONSIBILITY": (
        "Complete intent, canonical_name, owner_layer, lifecycle, "
        "location.path, location.symbol, and location.symbol_type."
    ),
    "PYTHON_PARSE_ERROR": (
        "Fix the Python syntax error before running verification again."
    ),
    "INVALID_BLUEPRINT": (
        "Fix bpfw/blueprint.yaml so it can be parsed and loaded."
    ),
}


def _render_block_finding(finding: Finding) -> str:
    """Render a single block finding as human-readable text."""
    lines: list[str] = []

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
    sections: list[str] = []

    # Header
    if report.allowed:
        sections.append("BPFW VERIFY PASSED")
    else:
        sections.append("BPFW VERIFY BLOCKED")

    sections.append("")

    # Authority
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
    if report.allowed:
        sections.append("Execution:")
        sections.append("  ALLOWED")
    else:
        sections.append("Execution:")
        sections.append("  BLOCKED")

    # Blocked findings detail
    block_findings = [
        finding for finding in report.findings
        if finding.severity == FINDING_SEVERITY_BLOCK
    ]

    if block_findings:
        sections.append("")
        for finding in block_findings:
            sections.append(_render_block_finding(finding))
            sections.append("")

    return "\n".join(sections)
