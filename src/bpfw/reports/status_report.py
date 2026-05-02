"""Status report rendering for BPFW MVP Catalog Mode."""

from pathlib import Path
from typing import Dict, List, Tuple

from bpfw.catalog.lifecycle import count_lifecycles
from bpfw.catalog.loader import BlueprintLoader
from bpfw.catalog.models import (
    AUTHORITY_STATE_DEFINED,
    AUTHORITY_STATE_DRAFT,
    AUTHORITY_STATE_EMPTY,
    AUTHORITY_STATE_INVALID,
    AUTHORITY_STATE_MISSING,
    VerificationReport,
)
from bpfw.catalog.verify import run_verify
from bpfw.protection.authority import get_blueprint_lock_state

_BLUEPRINT_DISPLAY_PATH = "bpfw/blueprint.yaml"


def _suggest_next_command(report: VerificationReport, lock_state: str) -> tuple[str, str]:
    """Return the passive next command suggestion for the current status."""

    if report.authority_state == AUTHORITY_STATE_MISSING:
        return "bpfw init", "No blueprint authority exists yet."

    if report.authority_state == AUTHORITY_STATE_INVALID:
        return "bpfw editor", "The blueprint authority is invalid and needs direct correction."

    has_structural_problem = (
        report.duplicate_active_intent_count
        or report.invalid_lifecycle_count
        or report.missing_declared_count
    )
    if has_structural_problem:
        return "bpfw editor", "The existing blueprint authority has structural problems."

    if report.undeclared_count or report.incomplete_responsibility_count:
        return "bpfw inspect", "Some detected code units are not declared or are incomplete."

    if (
        report.authority_state == AUTHORITY_STATE_EMPTY
        and report.declared_count == 0
        and report.discovered_count == 0
    ):
        return "bpfw plan", "No responsibilities are declared yet."

    if (
        report.authority_state in {AUTHORITY_STATE_DRAFT, AUTHORITY_STATE_DEFINED}
        and report.allowed
        and lock_state == "unlocked"
    ):
        return "bpfw lock", "The blueprint authority is valid but unlocked."

    return "bpfw verify", "Verify code and blueprint alignment."


def _determine_lock_state(project_root: Path, authority_state: str) -> str:
    """Determine the lock state for the blueprint.

    Returns one of: locked, degraded, unlocked, unknown.
    """
    if authority_state == AUTHORITY_STATE_MISSING:
        return "unknown"

    return get_blueprint_lock_state(project_root=project_root)


def run_status(project_root: Path) -> Tuple[str, int]:
    """Run the status pipeline and return formatted output with exit code.

    Pipeline:
    1. Resolve project_root.
    2. Load blueprint.
    3. Determine blueprint state.
    4. Determine lock state.
    5. If state is missing: do not scan, render allowed.
    6. If state is empty: do not scan, render allowed.
    7. If state is invalid: render blocked.
    8. If state is draft or defined: run verify pipeline, render result.

    Parameters
    ----------
    project_root:
        Root directory of the project.

    Returns
    -------
    tuple[str, int]
        Formatted status output and exit code (0 = allowed, 1 = blocked).
    """
    resolved_root = project_root.resolve()

    # Step 2: Load blueprint
    loader = BlueprintLoader(project_root=resolved_root)
    load_result = loader.load()

    # Step 3: Authority state from load result
    authority_state = load_result.state

    # Step 4: Lock state
    lock_state = _determine_lock_state(
        project_root=resolved_root,
        authority_state=authority_state,
    )

    # Lifecycle counts from loaded responsibilities
    lifecycle_counts = count_lifecycles(load_result.data)

    # Step 5: Missing — no scan, execution allowed
    if authority_state == AUTHORITY_STATE_MISSING:
        report = VerificationReport(
            authority_state=AUTHORITY_STATE_MISSING,
            allowed=True,
            findings=load_result.findings,
        )
        output = render_status_report(
            report=report,
            blueprint_path=_BLUEPRINT_DISPLAY_PATH,
            lock_state=lock_state,
            lifecycle_counts=lifecycle_counts,
        )
        return output, 0

    # Step 6: Empty — no scan, execution allowed
    if authority_state == AUTHORITY_STATE_EMPTY:
        report = VerificationReport(
            authority_state=AUTHORITY_STATE_EMPTY,
            allowed=True,
            findings=load_result.findings,
        )
        output = render_status_report(
            report=report,
            blueprint_path=_BLUEPRINT_DISPLAY_PATH,
            lock_state=lock_state,
            lifecycle_counts=lifecycle_counts,
        )
        return output, 0

    # Step 7: Invalid — render blocked
    if authority_state == AUTHORITY_STATE_INVALID:
        report = VerificationReport(
            authority_state=AUTHORITY_STATE_INVALID,
            allowed=False,
            findings=load_result.findings,
        )
        output = render_status_report(
            report=report,
            blueprint_path=_BLUEPRINT_DISPLAY_PATH,
            lock_state=lock_state,
            lifecycle_counts=lifecycle_counts,
        )
        return output, 1

    # Step 8: Draft or defined — run full verify pipeline
    report, verify_exit_code = run_verify(project_root=resolved_root)
    output = render_status_report(
        report=report,
        blueprint_path=_BLUEPRINT_DISPLAY_PATH,
        lock_state=lock_state,
        lifecycle_counts=lifecycle_counts,
    )
    return output, verify_exit_code


def render_status_report(
    report: VerificationReport,
    blueprint_path: str,
    lock_state: str,
    lifecycle_counts: Dict[str, int],
) -> str:
    """Render a VerificationReport and status context into a human-readable string.

    Parameters
    ----------
    report:
        The verification report with blueprint state, counts, and allowed flag.
    blueprint_path:
        Display path for the blueprint file (e.g. ``bpfw/blueprint.yaml``).
    lock_state:
        Lock status string: locked, degraded, unlocked, unsupported, or unknown.
    lifecycle_counts:
        Dict with keys ``active``, ``experimental``, ``legacy``, ``deprecated``
        mapping to their respective counts from loaded responsibilities.

    Returns
    -------
    str
        Formatted multi-line status report ready for terminal output.
    """
    lines: List[str] = []

    lines.append("BPFW STATUS")
    lines.append("")

    # Blueprint section
    lines.append("Blueprint:")
    lines.append(f"  path: {blueprint_path}")
    lines.append(f"  state: {report.authority_state}")
    lines.append(f"  lock: {lock_state}")
    lines.append("")

    # Responsibilities section
    lines.append("Responsibilities:")
    lines.append(f"  declared: {report.declared_count}")
    lines.append(f"  incomplete: {report.incomplete_responsibility_count}")
    lines.append("")

    # Code section
    lines.append("Code:")
    lines.append(f"  discovered: {report.discovered_count}")
    lines.append(f"  undeclared: {report.undeclared_count}")
    lines.append(f"  missing declared: {report.missing_declared_count}")
    lines.append("")

    # Lifecycle section
    lines.append("Lifecycle:")
    lines.append(f"  active: {lifecycle_counts.get('active', 0)}")
    lines.append(f"  experimental: {lifecycle_counts.get('experimental', 0)}")
    lines.append(f"  legacy: {lifecycle_counts.get('legacy', 0)}")
    lines.append(f"  deprecated: {lifecycle_counts.get('deprecated', 0)}")
    lines.append(f"  duplicate active intents: {report.duplicate_active_intent_count}")
    lines.append("")

    # Execution section
    if report.allowed:
        lines.append("Execution:")
        lines.append("  allowed")
    else:
        lines.append("Execution:")
        lines.append("  blocked")

    suggested_command, reason = _suggest_next_command(report=report, lock_state=lock_state)
    lines.append("")
    lines.append("Suggested next command:")
    lines.append(f"  {suggested_command}")
    lines.append("")
    lines.append("Reason:")
    lines.append(f"  {reason}")

    return "\n".join(lines)
