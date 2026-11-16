"""Verification flow for BPFW catalog mode."""

from pathlib import Path
from collections import Counter
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
    BlueprintLoadResult,
)
from bpfw.core.catalog.scan_strategy import ProjectScanStrategyFactory, ScanMode
from bpfw.core.catalog.scanner import include_declared_python_units
from bpfw.core.catalog.verification_cache import (
    _load_cached_verification_report,
    _load_fast_cached_verification_report,
    _save_cached_verification_report,
)
from bpfw.core.catalog.code_duplicates import CodeDuplicateAnalyzer
from bpfw.core.catalog.code_outcomes import CodeOutcomeAnalyzer
from bpfw.core.catalog.duplicate_profile import DuplicateActiveProfileRule, DuplicateProfileBuilder
from bpfw.core.catalog.security import validate_no_blueprint_secrets
from bpfw.core.catalog.validation import validate_blueprint_structure
from bpfw.core.source.registry import iter_source_files
from bpfw.core.source.tree_sitter_adapter import normalize_markup_granularity
from bpfw.reports.finding import FINDING_SEVERITY_BLOCK, FINDING_SEVERITY_WARNING, Finding

# Finding codes used for counting.
CODE_MISSING_DECLARED = "MISSING_DECLARED_CODE"
CODE_UNDECLARED = "UNDECLARED_CODE"
CODE_DUPLICATE_ACTIVE_PURPOSE = "DUPLICATE_ACTIVE_PURPOSE"
CODE_DUPLICATE_ACTIVE_PROFILE = "DUPLICATE_ACTIVE_PROFILE"
CODE_DUPLICATE_PROFILE_REVIEW = "DUPLICATE_PROFILE_REVIEW"
CODE_INVALID_LIFECYCLE = "INVALID_STATUS"
CODE_INCOMPLETE_RESPONSIBILITY = "INCOMPLETE_BLOCK"

DEFAULT_SOURCE_ROOTS = ["src", "app"]
DEFAULT_IGNORED_PATHS = [
    ".git",
    ".bpfw",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "tests",
    "migrations",
    "target",
    "vendor",
    "build",
    "dist",
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


def read_markup_granularity(
    blueprint_data: dict,
    domain_document: BlueprintDocument | None = None,
) -> str:
    """Read project.markup_granularity ("full" or "meaningful"); "full" when absent."""
    value = None
    if domain_document is not None:
        value = domain_document.project.get("markup_granularity")
    if value is None:
        project = blueprint_data.get("project") if isinstance(blueprint_data, dict) else None
        if isinstance(project, dict):
            value = project.get("markup_granularity")
    return normalize_markup_granularity(value)


def scan_project_from_blueprint(
    project_root: Path,
    blueprint_data: dict,
    domain_document: BlueprintDocument | None = None,
) -> ScanResult:
    """Run one Python code tree scan using source and ignore settings from blueprint data."""

    source_roots = read_source_roots(blueprint_data, domain_document=domain_document)
    ignored_paths = read_ignored_paths(blueprint_data, domain_document=domain_document)
    scanner = ProjectScanStrategyFactory().create(ScanMode.CACHE_ENABLED)
    result = scanner.scan(
        project_root=project_root,
        source_roots=source_roots,
        ignored_paths=ignored_paths,
        markup_granularity=read_markup_granularity(blueprint_data, domain_document=domain_document),
    )
    return include_declared_python_units(result, blueprint_data, project_root, source_roots, ignored_paths)


def _validate_sharded_authority(project_root: Path, load_result: Any) -> List[Finding]:
    """Validate sharded authority structure and detect shard drift.

    Args:
        project_root: Project root directory.
        load_result: BlueprintLoader load result.

    Returns:
        List of shard validation findings.
    """
    findings = []

    # Simple authority remains supported for v1/v2. Shard-specific validation
    # only applies when the authority explicitly declares the sharded layout.
    authority = load_result.data.get("authority")
    if not isinstance(authority, dict):
        return findings

    layout = authority.get("layout")
    if layout != "sharded":
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
                evidence={"file": ".bpfw/blueprint.yaml"},
            )
        )
        return findings

    from bpfw.core.authority.sqlite.migration import active_backend
    sqlite_active = active_backend(project_root) == "sqlite"
    # Validate each include. On SQLite, includes are legacy logical provenance,
    # never required physical authority files.
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

        # Check include is under .bpfw/blocks
        if not include_path.startswith(".bpfw/blocks/"):
            findings.append(
                Finding(
                    source="verify_sharded_authority",
                    code="INCLUDE_OUTSIDE_BLOCKS_DIR",
                    severity=FINDING_SEVERITY_BLOCK,
                    message=f"Include must be under .bpfw/blocks/: '{include_path}'",
                    evidence={"include": include_path},
                )
            )
            continue

        # Check include file exists
        full_path = project_root / include_path
        if not sqlite_active and not full_path.exists():
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
    if getattr(load_result, "authority_document", None) is not None:
        root_index_data = load_result.authority_document.index.data
    else:
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
                evidence={"file": ".bpfw/blueprint.yaml", "block_count": len(blocks)},
            )
        )

    # Use the already loaded authority document when available. This avoids
    # reloading every shard a second time during the same verify command.
    try:
        repository = AuthorityRepository(project_root)
        document = load_result.authority_document
        if document is None:
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
    source_roots: List[str] | None = None,
    source_file_counts: dict[str, int] | None = None,
    discovered_by_language: dict[str, int] | None = None,
    logical_component_count: int = 0,
    code_component_count: int = 0,
) -> VerificationReport:
    """Build a VerificationReport with computed counts and allowed flag."""
    missing_declared_count = sum(1 for finding in findings if finding.code == CODE_MISSING_DECLARED)
    undeclared_count = sum(1 for finding in findings if finding.code == CODE_UNDECLARED)
    duplicate_active_purpose_count = sum(1 for finding in findings if finding.code == CODE_DUPLICATE_ACTIVE_PURPOSE)
    duplicate_active_profile_count = sum(1 for finding in findings if finding.code == CODE_DUPLICATE_ACTIVE_PROFILE)
    duplicate_profile_review_count = sum(1 for finding in findings if finding.code == CODE_DUPLICATE_PROFILE_REVIEW)
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
        duplicate_active_profile_count=duplicate_active_profile_count,
        duplicate_profile_review_count=duplicate_profile_review_count,
        invalid_lifecycle_count=invalid_lifecycle_count,
        incomplete_responsibility_count=incomplete_responsibility_count,
        source_roots=list(source_roots or []),
        source_file_counts=dict(source_file_counts or {}),
        discovered_by_language=dict(discovered_by_language or {}),
        logical_component_count=logical_component_count,
        code_component_count=code_component_count,
    )


def _scan_diagnostics(
    project_root: Path,
    source_roots: List[str],
    ignored_paths: List[str],
    scan_result: ScanResult,
    code_component_count: int,
) -> tuple[List[Finding], dict[str, int], dict[str, int]]:
    """Explain missing roots, absent adapters, and zero-unit scans explicitly."""

    findings: List[Finding] = []
    missing_roots = [root for root in source_roots if not (project_root / root).is_dir()]
    for root in missing_roots:
        findings.append(Finding(
            source="bpfw",
            code="SOURCE_ROOT_MISSING",
            severity=FINDING_SEVERITY_WARNING,
            message=f"Configured source root does not exist: {root}",
            path=root,
            evidence={"source_root": root},
        ))

    file_counts = Counter(
        definition.identifier
        for _absolute, _relative, definition in iter_source_files(
            project_root, source_roots, ignored_paths
        )
    )
    discovered_counts = Counter(unit.language for unit in scan_result.discovered_units)
    supported_file_total = sum(file_counts.values())
    if code_component_count and supported_file_total == 0:
        findings.append(Finding(
            source="bpfw",
            code="NO_SUPPORTED_SOURCE_FILES",
            severity=FINDING_SEVERITY_BLOCK,
            message="No supported source files were found under the configured source roots.",
            evidence={"source_roots": source_roots},
        ))
    elif code_component_count and supported_file_total and not scan_result.discovered_units:
        findings.append(Finding(
            source="bpfw",
            code="NO_CODE_UNITS_DISCOVERED",
            severity=FINDING_SEVERITY_BLOCK,
            message=(
                "Supported source files exist, but no code units were extracted. "
                "Check optional language adapters and parse findings."
            ),
            evidence={"source_roots": source_roots, "source_file_counts": dict(file_counts)},
        ))
    return findings, dict(sorted(file_counts.items())), dict(sorted(discovered_counts.items()))


def run_verify(
    project_root: Path,
    precomputed_scan_result: ScanResult | None = None,
    precomputed_load_result: BlueprintLoadResult | None = None,
    *,
    deep: bool = False,
    capture_history: bool = True,
) -> Tuple[VerificationReport, int]:
    """Execute the complete verify pipeline."""
    resolved_root = project_root.resolve()

    can_try_fast_cache = precomputed_scan_result is None and precomputed_load_result is None and not deep
    if can_try_fast_cache:
        fast_cached_result = _load_fast_cached_verification_report(project_root=resolved_root)
        if fast_cached_result is not None:
            return fast_cached_result

    # Step 1-2: Load blueprint
    if precomputed_load_result is None:
        loader = BlueprintLoader(project_root=resolved_root)
        load_result = loader.load()
    else:
        load_result = precomputed_load_result

    # Step 2.5: Validate sharded authority structure
    shard_findings = _validate_sharded_authority(resolved_root, load_result)
    from bpfw.core.authority.sqlite.diagnostics import sqlite_findings
    shard_findings.extend(sqlite_findings(resolved_root))

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

    source_roots = read_source_roots(load_result.data, domain_document=load_result.domain_document)
    ignored_paths = read_ignored_paths(load_result.data, domain_document=load_result.domain_document)
    blueprint_version = load_result.data.get("version", 1) if isinstance(load_result.data, dict) else 1
    can_use_report_cache = precomputed_scan_result is None and not deep and blueprint_version != 2
    if can_use_report_cache:
        cached_result = _load_cached_verification_report(
            project_root=resolved_root,
            load_result=load_result,
            source_roots=source_roots,
            ignored_paths=ignored_paths,
        )
        if cached_result is not None:
            return cached_result

    # Step 6: Draft or defined - run scan, validation, drift
    if precomputed_scan_result is None:
        scan_result = scan_project_from_blueprint(
            project_root=resolved_root,
            blueprint_data=load_result.data,
            domain_document=load_result.domain_document,
        )
    else:
        scan_result = precomputed_scan_result

    scan_result = include_declared_python_units(scan_result, load_result.data, resolved_root, source_roots, ignored_paths)

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

    blocks = load_result.data.get("blocks", [])
    block_items = blocks if isinstance(blocks, list) else []
    code_component_count = sum(
        1 for block in block_items
        if isinstance(block, dict) and str(block.get("kind") or "code").strip().lower() == "code"
    )
    logical_component_count = sum(1 for block in block_items if isinstance(block, dict)) - code_component_count
    diagnostic_findings, source_file_counts, discovered_by_language = _scan_diagnostics(
        resolved_root, source_roots, ignored_paths, scan_result, code_component_count
    )
    duplicate_profiles = DuplicateProfileBuilder(
        project_root=resolved_root,
        discovered_units=scan_result.discovered_units,
        source_repository=scan_result.source_repository,
        blocks=blocks if isinstance(blocks, list) else [],
    ).build()
    duplicate_profile_findings = DuplicateActiveProfileRule().validate(
        blocks=blocks if isinstance(blocks, list) else [],
        profiles_by_key=duplicate_profiles,
    )

    code_duplicate_findings = CodeDuplicateAnalyzer(
        project_root=resolved_root,
        discovered_units=scan_result.discovered_units,
        source_repository=scan_result.source_repository,
    ).analyze()

    code_outcome_findings = CodeOutcomeAnalyzer(
        project_root=resolved_root,
        discovered_units=scan_result.discovered_units,
        source_repository=scan_result.source_repository,
    ).analyze()

    # Combine all findings
    all_findings: List[Finding] = []
    all_findings.extend(load_result.findings)
    all_findings.extend(shard_findings)
    all_findings.extend(scan_result.findings)
    all_findings.extend(diagnostic_findings)
    all_findings.extend(validation_findings)
    all_findings.extend(security_findings)
    all_findings.extend(drift_findings)
    all_findings.extend(duplicate_profile_findings)
    all_findings.extend(code_duplicate_findings)
    all_findings.extend(code_outcome_findings)

    # Alpha.13 first-class artifact validation. Explicit v2 artifacts may point
    # at code, prompts, config selectors, specs, skills, schemas, or generic files.
    if isinstance(load_result.data, dict) and int(load_result.data.get("version", 1) or 1) >= 2:
        try:
            from bpfw.core.artifacts import ArtifactResolver
            artifact_resolver = ArtifactResolver(resolved_root)
            for block in block_items:
                if not isinstance(block, dict):
                    continue
                block_id = str(block.get("id") or "-")
                explicit_artifacts = block.get("artifacts")
                profiles = load_result.data.get("profiles") if isinstance(load_result.data.get("profiles"), dict) else {}
                if isinstance(explicit_artifacts, list):
                    for explicit_artifact in explicit_artifacts:
                        if not isinstance(explicit_artifact, dict):
                            continue
                        profile_name = explicit_artifact.get("profile")
                        if isinstance(profile_name, str) and profile_name not in profiles:
                            all_findings.append(Finding(
                                source="artifact_resolution", code="UNKNOWN_ARTIFACT_PROFILE", severity="block",
                                message=f"Blueprint artifact profile '{profile_name}' for '{block_id}' is not defined.",
                                path=str(explicit_artifact.get("path") or ""),
                                evidence={"block": block_id, "artifact": explicit_artifact.get("id"), "profile": profile_name},
                                category="logical_drift", confidence="high",
                            ))
                artifacts = block.get("__bpfw_effective_artifacts")
                if not isinstance(artifacts, list):
                    artifacts = explicit_artifacts
                if not isinstance(artifacts, list):
                    continue
                for artifact in artifacts:
                    if not isinstance(artifact, dict):
                        continue
                    artifact_id = str(artifact.get("id") or artifact.get("symbol") or artifact.get("path") or "artifact")
                    resolved_artifact = artifact_resolver.resolve(artifact)
                    required = artifact.get("required", True) is not False
                    absolute_artifact_path = resolved_root / str(artifact.get("path") or "")
                    if not absolute_artifact_path.is_file():
                        all_findings.append(Finding(
                            source="artifact_resolution", code="ARTIFACT_MISSING",
                            severity="block" if required else "warning",
                            message=f"Blueprint artifact '{artifact_id}' for '{block_id}' is missing.",
                            path=str(artifact.get("path") or ""), symbol=str(artifact.get("symbol") or ""),
                            evidence={"block": block_id, "artifact": artifact_id, "required": required},
                            category="logical_drift", confidence="high",
                        ))
                    elif not resolved_artifact.resolved:
                        all_findings.append(Finding(
                            source="artifact_resolution", code="ARTIFACT_UNRESOLVED",
                            severity="block" if required else "warning",
                            message=f"Blueprint artifact '{artifact_id}' for '{block_id}' could not be resolved to its declared source region.",
                            path=resolved_artifact.path, symbol=resolved_artifact.symbol or "",
                            evidence={"block": block_id, "artifact": artifact_id, "parser": resolved_artifact.parser, "reason": resolved_artifact.message},
                            category="logical_drift", confidence="high",
                        ))
        except Exception as artifact_error:
            all_findings.append(Finding(
                source="artifact_resolution", code="ARTIFACT_RESOLVER_ERROR", severity="warning",
                message=f"Artifact verification could not complete: {artifact_error}",
                evidence={"reason": str(artifact_error)}, category="logical_drift", confidence="medium",
            ))

    # Alpha.13: high-confidence non-code files referenced by runtime code are
    # architectural candidates.  Report them when no Blueprint artifact binds them.
    if isinstance(load_result.data, dict) and int(load_result.data.get("version", 1) or 1) >= 2:
        try:
            from bpfw.core.artifacts.flow import discover_flow_artifact_candidates
            for candidate in discover_flow_artifact_candidates(resolved_root, load_result.data):
                all_findings.append(Finding(
                    source="artifact_flow",
                    code="UNBOUND_FLOW_ARTIFACT",
                    severity="warning",
                    message=(f"Runtime code references architectural artifact '{candidate['path']}' "
                             "but no Blueprint artifact binds it."),
                    path=candidate["path"],
                    evidence=candidate,
                    category="logical_drift",
                    confidence="high",
                ))
        except Exception:
            pass

    # Blueprint v2 system verification: declared intent, typed relationships,
    # logical invariants, interaction risks and intent continuity. Legacy v1
    # blueprints keep their previous behavior.
    if load_result.domain_document is not None and (load_result.domain_document.version or 1) >= 2:
        from bpfw.core.graph import SystemGraphBuilder
        from bpfw.core.intent import IntentContinuityManager
        from bpfw.core.verification import SystemVerificationEngine, VerificationContext

        system_graph = SystemGraphBuilder().build(
            load_result.domain_document,
            scan_result=scan_result,
            project_root=resolved_root,
        )
        system_context = VerificationContext(
            project_root=resolved_root,
            blueprint=load_result.domain_document,
            raw_blueprint=load_result.data,
            graph=system_graph,
            scan_result=scan_result,
        )
        all_findings.extend(SystemVerificationEngine().verify(system_context))
        all_findings.extend(IntentContinuityManager(resolved_root).check(load_result.domain_document))

        from bpfw.core.evidence.runner import EvidenceRunner
        evidence_runner = EvidenceRunner(resolved_root)
        if deep:
            _records, evidence_findings = evidence_runner.run(load_result.domain_document)
            all_findings.extend(evidence_findings)
        else:
            all_findings.extend(evidence_runner.freshness_findings(load_result.domain_document))

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
        source_roots=source_roots,
        source_file_counts=source_file_counts,
        discovered_by_language=discovered_by_language,
        logical_component_count=logical_component_count,
        code_component_count=code_component_count,
    )

    # Step 7-9: Exit codes
    exit_code = 0 if report.allowed else 1
    if can_use_report_cache:
        _save_cached_verification_report(
            project_root=resolved_root,
            load_result=load_result,
            source_roots=source_roots,
            ignored_paths=ignored_paths,
            report=report,
        )
    if capture_history:
        try:
            from bpfw.core.history.ledger import capture_artifact_state
            capture_artifact_state(resolved_root, load_result.data, trigger="verification")
        except Exception:
            # History must never make verification itself unavailable. The next run can retry.
            pass
    return report, exit_code
