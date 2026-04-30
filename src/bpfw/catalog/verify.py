"""Catalog Mode verify pipeline for BPFW MVP."""

from pathlib import Path
from typing import List, Tuple

from bpfw.catalog.drift import compare_declared_to_discovered
from bpfw.catalog.loader import BlueprintLoader
from bpfw.catalog.models import (
    AUTHORITY_STATE_DEFINED,
    AUTHORITY_STATE_DRAFT,
    AUTHORITY_STATE_EMPTY,
    AUTHORITY_STATE_INVALID,
    AUTHORITY_STATE_MISSING,
    VerificationReport,
)
from bpfw.catalog.scanner import scan_python_project
from bpfw.catalog.validation import validate_blueprint_structure
from bpfw.reports.finding import FINDING_SEVERITY_BLOCK, Finding

# Finding codes used for counting.
CODE_MISSING_DECLARED = "MISSING_DECLARED_CODE"
CODE_UNDECLARED = "UNDECLARED_CODE"
CODE_DUPLICATE_ACTIVE_INTENT = "DUPLICATE_ACTIVE_INTENT"
CODE_INVALID_LIFECYCLE = "INVALID_LIFECYCLE"
CODE_INCOMPLETE_RESPONSIBILITY = "INCOMPLETE_RESPONSIBILITY"

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

    # Step 3: Missing authority — allowed with info
    if load_result.state == AUTHORITY_STATE_MISSING:
        report = _build_report(
            authority_state=AUTHORITY_STATE_MISSING,
            findings=load_result.findings,
        )
        return report, 0

    # Step 4: Empty authority — allowed with warning
    if load_result.state == AUTHORITY_STATE_EMPTY:
        report = _build_report(
            authority_state=AUTHORITY_STATE_EMPTY,
            findings=load_result.findings,
        )
        return report, 0

    # Step 5: Invalid authority — blocked
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
    all_findings.extend(drift_findings)

    # Count declared responsibilities
    responsibilities = load_result.data.get("responsibilities")
    declared_count = len(responsibilities) if isinstance(responsibilities, list) else 0

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


# ---------------------------------------------------------------------------
# Legacy backward-compatible function used by core/registry.py pipelines
# (status command, engine routing).  Not part of the public MVP verify path.
# ---------------------------------------------------------------------------

from dataclasses import dataclass as _dataclass, field as _field

from bpfw.blueprint.models import BlueprintModel
from bpfw.init.scanner import MechanicalProjectScanner

_LEGACY_ALLOWED_LIFECYCLES = {"active", "experimental", "legacy", "deprecated"}


@_dataclass(slots=True)
class CatalogFinding:
    """Single verify finding (legacy)."""

    code: str
    status: str
    message: str
    resource: str


@_dataclass(slots=True)
class CatalogVerifyResult:
    """Catalog verify output (legacy)."""

    status: str
    findings: list[CatalogFinding] = _field(default_factory=list)
    summary: dict[str, str] = _field(default_factory=dict)


def _build_legacy_discovered_units(project_root: Path) -> set[str]:
    scanner = MechanicalProjectScanner()
    scan_result = scanner.scan(project_root=project_root)
    discovered_units: set[str] = set()
    for symbol in scan_result.symbols:
        if symbol.kind in {"class", "function"}:
            discovered_units.add(f"{symbol.file_path}::{symbol.name}")
    return discovered_units


def run_catalog_verify(project_root: Path, blueprint: BlueprintModel) -> CatalogVerifyResult:
    """Run catalog scanner, drift and lifecycle checks (legacy for engine pipeline)."""

    findings: list[CatalogFinding] = []
    declared_units: set[str] = set()
    duplicate_active_intents: dict[str, list[str]] = {}
    invalid_lifecycles = 0

    for responsibility in blueprint.responsibilities:
        lifecycle_state = (responsibility.lifecycle_state or "").strip().lower()
        if lifecycle_state not in _LEGACY_ALLOWED_LIFECYCLES:
            invalid_lifecycles += 1
            findings.append(
                CatalogFinding(
                    code="INVALID_LIFECYCLE",
                    status="block",
                    message=(
                        f"Responsibility `{responsibility.responsibility_id}` has invalid lifecycle_state "
                        f"`{responsibility.lifecycle_state}`"
                    ),
                    resource=str(blueprint.source_path or "bpfw/blueprint.yaml"),
                )
            )

        intent_text = (responsibility.intent or "").strip().lower()
        if lifecycle_state == "active" and intent_text:
            duplicate_active_intents.setdefault(intent_text, []).append(responsibility.responsibility_id)

        allowed_files = set(responsibility.allowed_files)
        active_implementation_id = responsibility.active_implementation
        active_implementation = next(
            (item for item in responsibility.allowed_implementations if item.implementation_id == active_implementation_id),
            None,
        )

        for symbol_name in responsibility.allowed_symbols:
            if "." in symbol_name:
                continue
            for allowed_file in allowed_files:
                declared_units.add(f"{allowed_file}::{symbol_name}")

        if active_implementation is not None and active_implementation.class_name:
            declared_units.add(f"{active_implementation.file}::{active_implementation.class_name}")

    for intent_text, responsibility_ids in sorted(duplicate_active_intents.items()):
        if len(responsibility_ids) > 1:
            findings.append(
                CatalogFinding(
                    code="DUPLICATE_ACTIVE_INTENT",
                    status="block",
                    message=(
                        f"intent `{intent_text}` has multiple active responsibilities: "
                        + ", ".join(sorted(responsibility_ids))
                    ),
                    resource=str(blueprint.source_path or "bpfw/blueprint.yaml"),
                )
            )

    discovered_units = _build_legacy_discovered_units(project_root=project_root)

    missing_declared_units = sorted(declared_units - discovered_units)
    undeclared_units = sorted(discovered_units - declared_units)

    for missing_unit in missing_declared_units:
        findings.append(
            CatalogFinding(
                code="MISSING_DECLARED_CODE",
                status="block",
                message=f"Declared code unit is missing in project: {missing_unit}",
                resource=missing_unit,
            )
        )

    for undeclared_unit in undeclared_units:
        findings.append(
            CatalogFinding(
                code="UNDECLARED_CODE",
                status="block",
                message=f"Code unit exists but is not declared in blueprint: {undeclared_unit}",
                resource=undeclared_unit,
            )
        )

    blocked_findings = [item for item in findings if item.status == "block"]
    status = "block" if blocked_findings else "ok"

    return CatalogVerifyResult(
        status=status,
        findings=findings,
        summary={
            "declared_units": str(len(declared_units)),
            "discovered_units": str(len(discovered_units)),
            "missing_declared_code": str(len(missing_declared_units)),
            "undeclared_code": str(len(undeclared_units)),
            "duplicate_active_intents": str(
                len([intent for intent, responsibility_ids in duplicate_active_intents.items() if len(responsibility_ids) > 1])
            ),
            "invalid_lifecycles": str(invalid_lifecycles),
        },
    )
