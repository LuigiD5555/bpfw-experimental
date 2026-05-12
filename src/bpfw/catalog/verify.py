"""Catalog Mode verify pipeline for BPFW MVP."""

from pathlib import Path
from typing import List, Tuple

from bpfw.catalog.drift import compare_declared_to_discovered
from bpfw.catalog.loader import BlueprintLoader
from bpfw.catalog.models import (
    AUTHORITY_STATE_EMPTY,
    AUTHORITY_STATE_INVALID,
    AUTHORITY_STATE_MISSING,
    VerificationReport,
)
from bpfw.catalog.scanner import scan_python_project
from bpfw.catalog.security import validate_no_blueprint_secrets
from bpfw.catalog.validation import validate_blueprint_structure
from bpfw.catalog.schema import get_blocks
from bpfw.reports.finding import FINDING_SEVERITY_BLOCK, Finding

# Finding codes used for counting.
CODE_MISSING_DECLARED = "MISSING_DECLARED_CODE"
CODE_UNDECLARED = "UNDECLARED_CODE"
CODE_DUPLICATE_ACTIVE_INTENT = "DUPLICATE_ACTIVE_PURPOSE"
CODE_INVALID_LIFECYCLE = "INVALID_STATUS"
CODE_INCOMPLETE_RESPONSIBILITY = "INCOMPLETE_BLOCK"

_DEFAULT_SOURCE_ROOTS = ["src", "app"]
_DEFAULT_IGNORED_PATHS = [
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "tests",
    "migrations",
]


def _count_by_code(findings: List[Finding], code: str) -> int:
    """Count how many findings match the given code."""
    return sum(1 for finding in findings if finding.code == code)


def _read_source_roots(blueprint_data: dict) -> List[str]:
    """Read project.source_roots from blueprint, or return defaults."""
    project = blueprint_data.get("project")
    if isinstance(project, dict):
        source_roots = project.get("source_roots")
        if isinstance(source_roots, list) and source_roots:
            return [str(root) for root in source_roots]
    return list(_DEFAULT_SOURCE_ROOTS)


def _read_ignored_paths(blueprint_data: dict) -> List[str]:
    """Read project.ignored_paths from blueprint, or return defaults."""
    project = blueprint_data.get("project")
    if isinstance(project, dict):
        ignored_paths = project.get("ignored_paths")
        if isinstance(ignored_paths, list) and ignored_paths:
            return [str(path) for path in ignored_paths]
    return list(_DEFAULT_IGNORED_PATHS)


def _build_report(
    authority_state: str,
    findings: List[Finding],
    declared_count: int = 0,
    discovered_count: int = 0,
) -> VerificationReport:
    """Build a VerificationReport with computed counts and allowed flag."""
    missing_declared_count = _count_by_code(findings, CODE_MISSING_DECLARED)
    undeclared_count = _count_by_code(findings, CODE_UNDECLARED)
    duplicate_active_intent_count = _count_by_code(findings, CODE_DUPLICATE_ACTIVE_INTENT)
    invalid_lifecycle_count = _count_by_code(findings, CODE_INVALID_LIFECYCLE)
    incomplete_responsibility_count = _count_by_code(findings, CODE_INCOMPLETE_RESPONSIBILITY)

    has_block = any(
        finding.severity == FINDING_SEVERITY_BLOCK
        for finding in findings
    )

    return VerificationReport(
        authority_state=authority_state,
        allowed=not has_block,
        findings=findings,
        declared_count=declared_count,
        discovered_count=discovered_count,
        missing_declared_count=missing_declared_count,
        undeclared_count=undeclared_count,
        duplicate_active_intent_count=duplicate_active_intent_count,
        invalid_lifecycle_count=invalid_lifecycle_count,
        incomplete_responsibility_count=incomplete_responsibility_count,
    )


def run_verify(project_root: Path) -> Tuple[VerificationReport, int]:
    """Execute the complete MVP verify pipeline.

    Parameters
    ----------
    project_root:
        Root directory of the project to verify.

    Returns
    -------
    tuple[VerificationReport, int]
        The verification report and the exit code (0 = allowed,
        1 = blocked).
    """
    resolved_root = project_root.resolve()

    # Step 1-2: Load blueprint
    loader = BlueprintLoader(project_root=resolved_root)
    load_result = loader.load()

    # Step 3: Missing blueprint: allowed with info.
    if load_result.state == AUTHORITY_STATE_MISSING:
        report = _build_report(
            authority_state=AUTHORITY_STATE_MISSING,
            findings=load_result.findings,
        )
        return report, 0

    # Step 4: Empty blueprint: allowed with warning.
    if load_result.state == AUTHORITY_STATE_EMPTY:
        report = _build_report(
            authority_state=AUTHORITY_STATE_EMPTY,
            findings=load_result.findings,
        )
        return report, 0

    # Step 5: Invalid blueprint: blocked.
    if load_result.state == AUTHORITY_STATE_INVALID:
        report = _build_report(
            authority_state=AUTHORITY_STATE_INVALID,
            findings=load_result.findings,
        )
        return report, 1

    # Step 6: Draft or defined — run scan, validation, drift
    source_roots = _read_source_roots(load_result.data)
    ignored_paths = _read_ignored_paths(load_result.data)

    scan_result = scan_python_project(
        project_root=resolved_root,
        source_roots=source_roots,
        ignored_paths=ignored_paths,
    )

    validation_findings = validate_blueprint_structure(
        blueprint_data=load_result.data,
        authority_state=load_result.state,
    )

    # Security validation: detect secrets and absolute paths
    security_findings = validate_no_blueprint_secrets(load_result.data)

    # Drift comparison only for defined state
    drift_findings = compare_declared_to_discovered(
        blueprint_data=load_result.data,
        discovered_units=scan_result.discovered_units,
        authority_state=load_result.state,
    )

    # Combine all findings
    all_findings: List[Finding] = []
    all_findings.extend(load_result.findings)
    all_findings.extend(scan_result.findings)
    all_findings.extend(validation_findings)
    all_findings.extend(security_findings)
    all_findings.extend(drift_findings)

    # Count declared blocks
    blocks = get_blocks(load_result.data)
    declared_count = len(blocks) if isinstance(blocks, list) else 0

    discovered_count = len(scan_result.discovered_units)

    report = _build_report(
        authority_state=load_result.state,
        findings=all_findings,
        declared_count=declared_count,
        discovered_count=discovered_count,
    )

    # Step 7-9: Exit codes
    exit_code = 0 if report.allowed else 1
    return report, exit_code
