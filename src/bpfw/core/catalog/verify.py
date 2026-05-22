"""Catalog Mode verify pipeline for BPFW MVP."""

from pathlib import Path
from typing import Any, List, Tuple

from bpfw.core.authority.index import AuthorityIndex
from bpfw.core.authority import AuthorityRepository
from bpfw.core.catalog.drift import compare_declared_to_discovered
from bpfw.core.catalog.domain import BlueprintDocument
from bpfw.core.catalog.loader import BlueprintLoader
from bpfw.core.catalog.models import (
    AUTHORITY_STATE_EMPTY,
    AUTHORITY_STATE_INVALID,
    AUTHORITY_STATE_MISSING,
    VerificationReport,
    ScanResult,
)
from bpfw.core.catalog.scanner import scan_python_project
from bpfw.core.catalog.security import validate_no_blueprint_secrets
from bpfw.core.catalog.validation import validate_blueprint_structure
from bpfw.reports.finding import FINDING_SEVERITY_BLOCK, FINDING_SEVERITY_WARNING, Finding

# Finding codes used for counting.
CODE_MISSING_DECLARED = "MISSING_DECLARED_CODE"
CODE_UNDECLARED = "UNDECLARED_CODE"
CODE_DUPLICATE_ACTIVE_PURPOSE = "DUPLICATE_ACTIVE_PURPOSE"
CODE_INVALID_LIFECYCLE = "INVALID_STATUS"
CODE_INCOMPLETE_RESPONSIBILITY = "INCOMPLETE_BLOCK"

DEFAULT_SOURCE_ROOTS = ["src", "app"]
DEFAULT_IGNORED_PATHS = [
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "tests",
    "migrations",
]


def read_source_roots(
    blueprint_data: dict,
    domain_document: BlueprintDocument | None = None,
) -> List[str]:
    """Read project.source_roots from blueprint, or return defaults."""
    if domain_document is not None and domain_document.project.get("source_roots"):
        return [str(root) for root in domain_document.project.get("source_roots", [])]

    project = blueprint_data.get("project")
    if isinstance(project, dict):
        source_roots = project.get("source_roots")
        if isinstance(source_roots, list) and source_roots:
            return [str(root) for root in source_roots]
    return list(DEFAULT_SOURCE_ROOTS)


def read_ignored_paths(
    blueprint_data: dict,
    domain_document: BlueprintDocument | None = None,
) -> List[str]:
    """Read project.ignored_paths from blueprint, or return defaults."""
    if domain_document is not None and domain_document.project.get("ignored_paths"):
        return [str(path) for path in domain_document.project.get("ignored_paths", [])]

    project = blueprint_data.get("project")
    if isinstance(project, dict):
        ignored_paths = project.get("ignored_paths")
        if isinstance(ignored_paths, list) and ignored_paths:
            return [str(path) for path in ignored_paths]
    return list(DEFAULT_IGNORED_PATHS)


def scan_project_from_blueprint(
    project_root: Path,
    blueprint_data: dict,
    domain_document: BlueprintDocument | None = None,
) -> ScanResult:
    """Run one AST scan using source and ignore settings from blueprint data."""

    source_roots = read_source_roots(blueprint_data, domain_document=domain_document)
    ignored_paths = read_ignored_paths(blueprint_data, domain_document=domain_document)
    return scan_python_project(
        project_root=project_root,
        source_roots=source_roots,
        ignored_paths=ignored_paths,
    )


def _validate_sharded_authority(project_root: Path, load_result: Any) -> List[Finding]:
    """Validate sharded authority structure and detect shard drift.
    
    Args:
        project_root: Project root directory.
        load_result: BlueprintLoader load result.
    
    Returns:
        List of shard validation findings.
    """
    findings = []
    
    # Check if authority section exists
    authority = load_result.data.get("authority")
    if not isinstance(authority, dict):
        findings.append(
            Finding(
                source="verify_sharded_authority",
                code="MISSING_AUTHORITY_SECTION",
                severity=FINDING_SEVERITY_BLOCK,
                message="Missing 'authority' section in blueprint.yaml",
                evidence={"file": "bpfw/blueprint.yaml"},
            )
        )
        return findings
    
    # Validate layout is sharded
    layout = authority.get("layout")
    if layout != "sharded":
        findings.append(
            Finding(
                source="verify_sharded_authority",
                code="INVALID_AUTHORITY_LAYOUT",
                severity=FINDING_SEVERITY_BLOCK,
                message=f"Invalid authority layout: '{layout}'. Expected 'sharded'",
                evidence={"file": "bpfw/blueprint.yaml", "current": layout, "expected": "sharded"},
            )
        )
        return findings
    
    # Validate includes exists and is a list
    includes = load_result.data.get("includes")
    if not isinstance(includes, list) or not includes:
        findings.append(
            Finding(
                source="verify_sharded_authority",
                code="MISSING_OR_INVALID_INCLUDES",
                severity=FINDING_SEVERITY_BLOCK,
                message="Missing or invalid 'includes' in blueprint.yaml. Must be a non-empty list.",
                evidence={"file": "bpfw/blueprint.yaml"},
            )
        )
        return findings
    
    # Validate each include
    for include_path in includes:
        if not isinstance(include_path, str):
            findings.append(
                Finding(
                    source="verify_sharded_authority",
                    code="INVALID_INCLUDE_TYPE",
                    severity=FINDING_SEVERITY_BLOCK,
                    message=f"Include must be a string, got {type(include_path).__name__}",
                    evidence={"include": include_path},
                )
            )
            continue
        
        # Check for glob patterns
        if "*" in include_path or "?" in include_path:
            findings.append(
                Finding(
                    source="verify_sharded_authority",
                    code="GLOB_INCLUDE_NOT_ALLOWED",
                    severity=FINDING_SEVERITY_BLOCK,
                    message=f"Glob patterns not allowed in includes: '{include_path}'",
                    evidence={"include": include_path},
                )
            )
            continue
        
        # Check include is under bpfw/blocks
        if not include_path.startswith("bpfw/blocks/"):
            findings.append(
                Finding(
                    source="verify_sharded_authority",
                    code="INCLUDE_OUTSIDE_BLOCKS_DIR",
                    severity=FINDING_SEVERITY_BLOCK,
                    message=f"Include must be under bpfw/blocks/: '{include_path}'",
                    evidence={"include": include_path},
                )
            )
            continue
        
        # Check include file exists
        full_path = project_root / include_path
        if not full_path.exists():
            findings.append(
                Finding(
                    source="verify_sharded_authority",
                    code="INCLUDE_FILE_MISSING",
                    severity=FINDING_SEVERITY_BLOCK,
                    message=f"Included shard file does not exist: '{include_path}'",
                    evidence={"include": include_path, "full_path": str(full_path)},
                )
            )
    
    # Check for root-level blocks in the raw authority index only.
    # load_result.data is unified and intentionally includes shard blocks.
    try:
        root_index_data = AuthorityIndex.load(project_root).data
    except Exception:
        root_index_data = load_result.data
    blocks = root_index_data.get("blocks")
    if isinstance(blocks, list) and blocks:
        findings.append(
            Finding(
                source="verify_sharded_authority",
                code="ROOT_LEVEL_BLOCKS_NOT_ALLOWED",
                severity=FINDING_SEVERITY_BLOCK,
                message=f"Root blueprint.yaml contains {len(blocks)} block(s). Blocks must be in shard files only.",
                evidence={"file": "bpfw/blueprint.yaml", "block_count": len(blocks)},
            )
        )
    
    # Use AuthorityRepository to validate for duplicates and drift
    try:
        repository = AuthorityRepository(project_root)
        document = repository.load()
        validation_findings = repository.validate(document)
        
        # Convert authority validation findings to verify findings
        for vf in validation_findings:
            findings.append(
                Finding(
                    source="verify_sharded_authority",
                    code=vf.code,
                    severity=FINDING_SEVERITY_BLOCK if vf.severity == "error" else FINDING_SEVERITY_WARNING,
                    message=vf.message,
                    evidence=vf.details if hasattr(vf, 'details') else {},
                )
            )
    except Exception as e:
        findings.append(
            Finding(
                source="verify_sharded_authority",
                code="AUTHORITY_REPOSITORY_ERROR",
                severity=FINDING_SEVERITY_BLOCK,
                message=f"Failed to validate authority repository: {str(e)}",
                evidence={"error": str(e)},
            )
        )
    
    return findings


def _build_report(
    authority_state: str,
    findings: List[Finding],
    declared_count: int = 0,
    discovered_count: int = 0,
) -> VerificationReport:
    """Build a VerificationReport with computed counts and allowed flag."""
    missing_declared_count = sum(1 for finding in findings if finding.code == CODE_MISSING_DECLARED)
    undeclared_count = sum(1 for finding in findings if finding.code == CODE_UNDECLARED)
    duplicate_active_purpose_count = sum(1 for finding in findings if finding.code == CODE_DUPLICATE_ACTIVE_PURPOSE)
    invalid_lifecycle_count = sum(1 for finding in findings if finding.code == CODE_INVALID_LIFECYCLE)
    incomplete_responsibility_count = sum(1 for finding in findings if finding.code == CODE_INCOMPLETE_RESPONSIBILITY)

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
        duplicate_active_purpose_count=duplicate_active_purpose_count,
        invalid_lifecycle_count=invalid_lifecycle_count,
        incomplete_responsibility_count=incomplete_responsibility_count,
    )


def run_verify(
    project_root: Path,
    precomputed_scan_result: ScanResult | None = None,
) -> Tuple[VerificationReport, int]:
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

    # Step 2.5: Validate sharded authority structure
    shard_findings = _validate_sharded_authority(resolved_root, load_result)

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
    if precomputed_scan_result is None:
        scan_result = scan_project_from_blueprint(
            project_root=resolved_root,
            blueprint_data=load_result.data,
            domain_document=load_result.domain_document,
        )
    else:
        scan_result = precomputed_scan_result

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
    all_findings.extend(shard_findings)
    all_findings.extend(scan_result.findings)
    all_findings.extend(validation_findings)
    all_findings.extend(security_findings)
    all_findings.extend(drift_findings)

    # Count declared blocks
    if load_result.domain_document is not None:
        declared_count = len(load_result.domain_document.blocks)
    else:
        blocks = load_result.data.get("blocks", [])
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
