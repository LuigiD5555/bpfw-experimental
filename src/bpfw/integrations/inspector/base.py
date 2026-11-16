"""Shared inspector behavior for BPFW catalog completion."""
import ast
from functools import cmp_to_key
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, TYPE_CHECKING

from bpfw.core.catalog.access_control import ensure_blueprint_can_be_written
from bpfw.core.catalog.loader import BlueprintLoader
from bpfw.core.catalog.models import (
    AUTHORITY_STATE_INVALID,
    AUTHORITY_STATE_MISSING,
    BlueprintLoadResult,
    DiscoveredCodeUnit,
)
from bpfw.core.catalog.models import ScanResult
from bpfw.core.catalog.scan_strategy import ProjectScanStrategyFactory, ScanMode
from bpfw.core.catalog.verify import read_ignored_paths, read_source_roots, run_verify, scan_project_from_blueprint
from bpfw.core.errors import BlueprintLockedError
from bpfw.reports.finding import Finding
from bpfw.shared.text import to_snake_case
from bpfw.core.profiling import RuntimeProfiler
from bpfw.integrations.inspector.hierarchical_preview import _HierarchicalCodePreviewRenderer
from bpfw.core.artifacts import ArtifactResolver, block_artifacts, choose_primary_artifact

if TYPE_CHECKING:
    from bpfw.reports.verify_report import VerificationReport

_profiler = RuntimeProfiler()

ALLOWED_STATUSES = ("active", "experimental", "legacy", "deprecated")
REQUIRED_HUMAN_FIELDS = ("purpose", "domain", "status")
ISSUE_DRAFT = "draft"
ISSUE_NEW_DETECTED = "new_detected"


def _has_sharded_authority_layout(blueprint_data: Dict[str, Any] | None) -> bool:
    """Return True when blueprint data declares sharded authority layout."""

    if not isinstance(blueprint_data, dict):
        return False
    authority_data = blueprint_data.get("authority")
    if not isinstance(authority_data, dict):
        return False
    return authority_data.get("layout") == "sharded"


@dataclass(slots=True)
class InspectIssue:
    """One block-level item to review in inspector."""

    issue_type: str
    block: Dict[str, Any]
    add_on_accept: bool = False
    context_lines: list[str] = field(default_factory=list)


@dataclass(slots=True)
class InspectLoadResult:
    """Loaded inspect state or a blocking message."""

    project_root: Path
    blueprint_path: Path | None
    blueprint_data: Dict[str, Any]
    incomplete: List[Dict[str, Any]]
    issues: list[InspectIssue]
    authority_state: str
    authority_document: Any | None = None
    load_result: BlueprintLoadResult | None = None
    discovered_count: int = 0
    undeclared_count: int = 0
    missing_declared_count: int = 0
    drift_findings: list[Finding] | None = None
    scan_result: ScanResult | None = None
    verify_report: "VerificationReport | None" = None
    pre_inspection_context_lines: list[str] = field(default_factory=list)
    message: str | None = None
    exit_code: int = 0

    @property
    def blocked(self) -> bool:
        """Return True when inspect cannot continue."""

        return self.exit_code != 0


def load_inspect_session(
    project_root: Path,
    precomputed_scan_result: ScanResult | None = None,
    precomputed_verify_report: "VerificationReport | None" = None,
) -> InspectLoadResult:
    """Load blueprint data and return the inspect work set.

    Args:
        project_root: Root directory of the project.
        precomputed_scan_result: Optional scan result from engine to reuse.
        precomputed_verify_report: Optional verify report from engine to reuse.

    Returns:
        InspectLoadResult with loaded session data.
    """

    from bpfw.core.authority import AuthorityRepository
    from bpfw.integrations.shared.runtime_context import get_integration_runtime_cache

    with _profiler.measure("inspector.load_blueprint"):
        resolved_root = project_root.resolve()
        loader = BlueprintLoader(project_root=resolved_root)
        load_result = loader.load()

        # Try to get precomputed data from runtime cache first
        runtime_cache = get_integration_runtime_cache()
        cached_scan_result = runtime_cache.get("scan_result")
        cached_blueprint_data = runtime_cache.get("blueprint_data")
        cached_verify_report = runtime_cache.get("verify_report")

        # Use cached data if available, otherwise use parameters or scan fresh
        scan_result = cached_scan_result or precomputed_scan_result
        blueprint_data = cached_blueprint_data
        report = cached_verify_report or precomputed_verify_report

    if load_result.state == AUTHORITY_STATE_MISSING:
        return InspectLoadResult(
            project_root=resolved_root,
            blueprint_path=None,
            blueprint_data={},
            incomplete=[],
            issues=[],
            authority_state=load_result.state,
            message="BPFW Inspector\n\nInspector blocked.\nReason: No blueprint authority file was found.\nExpected: .bpfw/blueprint.yaml\nNext: Run bpfw init first.",
            exit_code=1,
        )

    if load_result.state == AUTHORITY_STATE_INVALID:
        return InspectLoadResult(
            project_root=resolved_root,
            blueprint_path=Path(load_result.path),
            blueprint_data={},
            incomplete=[],
            issues=[],
            authority_state=load_result.state,
            message="BPFW Inspector\n\nInspector blocked.\nReason: Blueprint authority could not be loaded.\nFile: .bpfw/blueprint.yaml\nError: Invalid YAML syntax.\nNext: Fix .bpfw/blueprint.yaml and run bpfw inspector again.",
            exit_code=1,
        )

    try:
        ensure_blueprint_can_be_written(project_root=resolved_root)
    except BlueprintLockedError:
        return InspectLoadResult(
            project_root=resolved_root,
            blueprint_path=Path(load_result.path),
            blueprint_data=load_result.data,
            incomplete=[],
            issues=[],
            authority_state=load_result.state,
            message="BPFW Inspector\n\nInspector blocked.\nReason: Authority is locked.\nProtected files: .bpfw/blueprint.yaml .bpfw/blocks/*.yaml\nNext: Run bpfw unlock before editing metadata.",
            exit_code=1,
        )

    with _profiler.measure("inspector.load_authority_document"):
        # Load authority document only for sharded authority.
        blueprint_for_authority_check = blueprint_data if isinstance(blueprint_data, dict) else load_result.data
        authority_document = None

        if _has_sharded_authority_layout(blueprint_for_authority_check):
            authority_document = load_result.authority_document
            if authority_document is None:
                repository = AuthorityRepository(resolved_root)
                authority_document = repository.load()

            # Always use canonical sharded authority data from repository.
            blueprint_data = authority_document.blueprint_data
        elif blueprint_data is None:
            # Simple blueprint.yaml - use data from loader
            blueprint_data = load_result.data

    with _profiler.measure("inspector.scan_project"):
        # Only scan if we don't have a precomputed result. Inspector/editor workflows
        # can write cache files, so they use the incremental scan cache.
        if scan_result is None:
            source_roots = read_source_roots(blueprint_data, domain_document=load_result.domain_document)
            ignored_paths = read_ignored_paths(blueprint_data, domain_document=load_result.domain_document)
            scanner = ProjectScanStrategyFactory().create(ScanMode.CACHE_ENABLED)
            scan_result = scanner.scan(
                project_root=resolved_root,
                source_roots=source_roots,
                ignored_paths=ignored_paths,
            )

    with _profiler.measure("inspector.run_verify"):
        # Only run verify if we don't have a precomputed report
        if report is None:
            report, _exit_code = run_verify(
                project_root=resolved_root,
                precomputed_scan_result=scan_result,
                precomputed_load_result=load_result,
            )

    drift_findings = [
        finding
        for finding in report.findings
        if finding.code in {"UNDECLARED_CODE", "MISSING_DECLARED_CODE"}
    ]
    system_context_lines: list[str] = []
    if isinstance(blueprint_data, dict) and int(blueprint_data.get("version", 1) or 1) >= 2:
        for finding in report.findings:
            if finding.category in {"intent_drift", "logical_drift", "behavioral_drift", "interaction_drift"}:
                system_context_lines.append(
                    f"{finding.severity.upper()} {finding.code}: {finding.message}"
                )
            if len(system_context_lines) >= 5:
                break

    with _profiler.measure("inspector.build_issues"):
        incomplete = get_incomplete_blocks(blueprint_data)
        issues = build_inspect_issues(
            blueprint_data=blueprint_data,
            incomplete=incomplete,
            scan_result=scan_result,
        )

    return InspectLoadResult(
        project_root=resolved_root,
        blueprint_path=Path(load_result.path),
        blueprint_data=blueprint_data,
        incomplete=incomplete,
        issues=issues,
        authority_state=load_result.state,
        authority_document=authority_document,
        load_result=load_result,
        discovered_count=report.discovered_count,
        undeclared_count=report.undeclared_count,
        missing_declared_count=report.missing_declared_count,
        drift_findings=drift_findings,
        scan_result=scan_result,
        verify_report=report,
        pre_inspection_context_lines=system_context_lines,
    )


def load_metadata_inspect_session(project_root: Path) -> InspectLoadResult:
    """Load inspector metadata work without scanning or running verify.

    The fast path first tries a persisted Inspector work cache. When authority
    files have not changed, this avoids reparsing all shards and rebuilding the
    same incomplete-metadata queue on every Inspector startup.

    Args:
        project_root: Root directory of the project.

    Returns:
        InspectLoadResult containing metadata-only inspector issues.
    """
    from bpfw.core.authority import AuthorityRepository
    from bpfw.integrations.inspector.work_cache import (
        InspectorWorkCacheRepository,
        build_authority_signature,
    )

    resolved_root = project_root.resolve()
    with _profiler.measure("inspector.metadata_only.authority_signature"):
        authority_signature = build_authority_signature(resolved_root)
    cache_repository = InspectorWorkCacheRepository(resolved_root)
    with _profiler.measure("inspector.metadata_only.load_work_cache"):
        cached_session = cache_repository.load_metadata_session(authority_signature)
    if cached_session is not None:
        try:
            ensure_blueprint_can_be_written(project_root=resolved_root)
        except BlueprintLockedError:
            cached_session.message = "BPFW Inspector\n\nInspector blocked.\nReason: Authority is locked.\nProtected files: .bpfw/blueprint.yaml .bpfw/blocks/*.yaml\nNext: Run bpfw unlock before editing metadata."
            cached_session.exit_code = 1
        return cached_session

    with _profiler.measure("inspector.metadata_only.load_blueprint"):
        loader = BlueprintLoader(project_root=resolved_root)
        load_result = loader.load()

    if load_result.state == AUTHORITY_STATE_MISSING:
        return InspectLoadResult(
            project_root=resolved_root,
            blueprint_path=None,
            blueprint_data={},
            incomplete=[],
            issues=[],
            authority_state=load_result.state,
            message="BPFW Inspector\n\nInspector blocked.\nReason: No blueprint authority file was found.\nExpected: .bpfw/blueprint.yaml\nNext: Run bpfw init first.",
            exit_code=1,
        )

    if load_result.state == AUTHORITY_STATE_INVALID:
        return InspectLoadResult(
            project_root=resolved_root,
            blueprint_path=Path(load_result.path),
            blueprint_data={},
            incomplete=[],
            issues=[],
            authority_state=load_result.state,
            message="BPFW Inspector\n\nInspector blocked.\nReason: Blueprint authority could not be loaded.\nFile: .bpfw/blueprint.yaml\nError: Invalid YAML syntax.\nNext: Fix .bpfw/blueprint.yaml and run bpfw inspector again.",
            exit_code=1,
        )

    try:
        ensure_blueprint_can_be_written(project_root=resolved_root)
    except BlueprintLockedError:
        return InspectLoadResult(
            project_root=resolved_root,
            blueprint_path=Path(load_result.path),
            blueprint_data=load_result.data,
            incomplete=[],
            issues=[],
            authority_state=load_result.state,
            message="BPFW Inspector\n\nInspector blocked.\nReason: Authority is locked.\nProtected files: .bpfw/blueprint.yaml .bpfw/blocks/*.yaml\nNext: Run bpfw unlock before editing metadata.",
            exit_code=1,
        )

    blueprint_data = load_result.data
    authority_document = None
    if _has_sharded_authority_layout(blueprint_data):
        with _profiler.measure("inspector.metadata_only.load_authority_document"):
            authority_document = load_result.authority_document
            if authority_document is None:
                repository = AuthorityRepository(resolved_root)
                authority_document = repository.load()
            blueprint_data = authority_document.blueprint_data

    with _profiler.measure("inspector.metadata_only.build_issues"):
        incomplete = get_incomplete_blocks(blueprint_data)
        issues = sort_inspect_issues_hierarchically(
            [InspectIssue(issue_type=ISSUE_DRAFT, block=block) for block in incomplete]
        )
    session = InspectLoadResult(
        project_root=resolved_root,
        blueprint_path=Path(load_result.path),
        blueprint_data=blueprint_data,
        incomplete=incomplete,
        issues=issues,
        authority_state=load_result.state,
        authority_document=authority_document,
        load_result=load_result,
        pre_inspection_context_lines=["Drift state: unchanged since last inspection."],
    )
    with _profiler.measure("inspector.metadata_only.save_work_cache"):
        cache_repository.save_metadata_session(authority_signature, session)
    return session


def _responsibility_key(block: Dict[str, Any]) -> tuple[str, str, str] | None:
    """Return the path, symbol, and kind key for a block."""

    location = block.get("code", {})
    if not isinstance(location, dict):
        return None

    path = clean_string(location.get("path"))
    symbol = clean_string(location.get("symbol"))
    symbol_type = clean_string(location.get("kind"))
    if path is None or symbol is None or symbol_type is None:
        return None
    return path, symbol, symbol_type



def split_issues_by_source_availability(
    project_root: Path,
    issues: list[InspectIssue],
) -> tuple[list[InspectIssue], list[InspectIssue]]:
    """Split inspector issues by whether their source file can be inspected.

    Metadata inspection is not allowed to handle structural drift. If a block
    points to a file that no longer exists, the item must go back through Drift
    Gate where the user can choose a package move, removal, legacy state, or a
    different structural decision.

    Args:
        project_root: Project root directory.
        issues: Candidate inspector issues.

    Returns:
        A tuple containing inspectable issues and structurally stale issues.
    """

    inspectable_issues: list[InspectIssue] = []
    stale_issues: list[InspectIssue] = []
    for issue in issues:
        if _issue_source_is_available(project_root=project_root, issue=issue):
            inspectable_issues.append(issue)
        else:
            stale_issues.append(issue)
    return inspectable_issues, stale_issues


def has_uninspectable_source_issues(project_root: Path, issues: list[InspectIssue]) -> bool:
    """Return whether any inspector issue points to unavailable source code.

    Args:
        project_root: Project root directory.
        issues: Inspector issues to validate.

    Returns:
        True when at least one issue cannot be resolved to an existing source
        file and therefore must be handled by Drift Gate.
    """

    return any(
        not _issue_source_is_available(project_root=project_root, issue=issue)
        for issue in issues
    )


def _issue_source_is_available(project_root: Path, issue: InspectIssue) -> bool:
    """Return whether an issue can be shown safely in Inspector.

    Args:
        project_root: Project root directory.
        issue: Inspector issue to validate.

    Returns:
        True when the referenced source file exists.
    """

    code_data = issue.block.get("code")
    if not isinstance(code_data, dict):
        return False
    relative_path = clean_string(code_data.get("path"))
    if relative_path is None:
        return False
    source_path = project_root / relative_path
    return source_path.exists()


def sort_inspect_issues_hierarchically(issues: list[InspectIssue]) -> list[InspectIssue]:
    """Return inspector issues in contained-to-container order.

    The Inspector should review child responsibilities before the parent that
    summarizes them. This preserves source order for unrelated blocks while
    forcing a parent such as ``AuthorityDocument`` to appear after children
    such as ``AuthorityDocument.get_blocks``.

    Args:
        issues: Inspector issues to order.

    Returns:
        Ordered inspector issues.
    """

    indexed_issues = list(enumerate(issues))

    def compare(left: tuple[int, InspectIssue], right: tuple[int, InspectIssue]) -> int:
        left_index, left_issue = left
        right_index, right_issue = right
        left_key = _issue_sort_data(left_issue)
        right_key = _issue_sort_data(right_issue)

        if left_key[0] != right_key[0]:
            return -1 if left_key[0] < right_key[0] else 1

        left_symbol = left_key[1]
        right_symbol = right_key[1]
        if _is_parent_symbol(left_symbol, right_symbol):
            return 1
        if _is_parent_symbol(right_symbol, left_symbol):
            return -1

        if left_key[2] != right_key[2]:
            return -1 if left_key[2] < right_key[2] else 1
        if left_key[3] != right_key[3]:
            return -1 if left_key[3] > right_key[3] else 1
        return left_index - right_index

    return [issue for _, issue in sorted(indexed_issues, key=cmp_to_key(compare))]


def _issue_sort_data(issue: InspectIssue) -> tuple[str, str, int, int]:
    """Return sortable code data for one inspector issue.

    Args:
        issue: Inspector issue.

    Returns:
        Path, symbol, start line, and symbol depth.
    """

    code_data = issue.block.get("code")
    if not isinstance(code_data, dict):
        return "", "", 10**9, 0
    path = clean_string(code_data.get("path")) or ""
    symbol = clean_string(code_data.get("symbol")) or ""
    start_line = code_data.get("start_line")
    if not isinstance(start_line, int):
        start_line = 10**9
    depth = len([part for part in symbol.split(".") if part])
    return path, symbol, start_line, depth


def _is_parent_symbol(parent_symbol: str, child_symbol: str) -> bool:
    """Return whether ``parent_symbol`` is a direct or indirect parent.

    Args:
        parent_symbol: Possible parent symbol.
        child_symbol: Possible child symbol.

    Returns:
        True when child is nested below parent.
    """

    if not parent_symbol or not child_symbol:
        return False
    return child_symbol.startswith(f"{parent_symbol}.")


def _discovered_key(unit: DiscoveredCodeUnit) -> tuple[str, str, str]:
    """Return the path, symbol, and kind key for discovered code."""

    return unit.path, unit.symbol, unit.symbol_type


def build_new_detected_responsibility(unit: DiscoveredCodeUnit) -> Dict[str, Any]:
    """Build a pending block from one newly detected code unit."""

    block = {
        "id": to_snake_case(unit.symbol),
        "purpose": None,
        "domain": None,
        "status": "active",
        "code": {
            "path": unit.path,
            "module": unit.module,
            "symbol": unit.symbol,
            "kind": unit.symbol_type,
            "language": unit.language,
            "unit_id": unit.canonical_id,
            "parent_unit_id": unit.parent_unit_id,
            "start_line": unit.start_line,
            "end_line": unit.end_line,
        },
        "detected": {
            "qualified_name": unit.qualified_name,
            "language": unit.language,
            "unit_id": unit.canonical_id,
            "visibility": unit.visibility,
            "kind": unit.symbol_type,
            "methods": unit.methods,
            "functions": unit.functions,
            "imports": unit.imports,
            "decorators": unit.decorators,
            "docstring": unit.docstring,
            "signature": unit.signature,
            "normalized_body_hash": unit.normalized_body_hash,
            "dangerous_capabilities": unit.dangerous_capabilities,
        },
        "entrypoints": [],
        "connections": [],
        "uniqueness": {
            "group": None,
            "allow_multiple_non_active": True,
            "forbid_active_duplicates": True,
            "suspected_duplicates": [],
        },
        "replacement": {
            "replaces": None,
            "replaced_by": None,
            "reason": None,
        },
        "notes": None,
    }

    # Add interface metadata if available
    if unit.interface_inputs or unit.interface_output:
        interface_data = {}
        if unit.interface_inputs:
            interface_data["inputs"] = unit.interface_inputs
        if unit.interface_output:
            interface_data["output"] = unit.interface_output
        if interface_data:
            block["interface"] = interface_data

    return block


def build_inspect_issues(
    blueprint_data: Dict[str, Any],
    incomplete: List[Dict[str, Any]],
    scan_result: ScanResult,
) -> list[InspectIssue]:
    """Build ordered inspect issues from incomplete and newly detected code."""

    issues = sort_inspect_issues_hierarchically(
        [InspectIssue(issue_type=ISSUE_DRAFT, block=block) for block in incomplete]
    )

    blocks = blueprint_data.get("blocks", [])
    if not isinstance(blocks, list):
        blocks = []

    declared_keys = {
        key
        for block in blocks
        if isinstance(block, dict)
        for key in [_responsibility_key(block)]
        if key is not None
    }

    # Complete blocks can still need a purely mechanical code-location refresh
    # (for example start/end lines after inserting code above a class). Keep that
    # work visible so Save/Next persists the synchronized location.
    incomplete_ids = {id(block) for block in incomplete}
    discovered_by_key = {
        (unit.path, unit.symbol, unit.symbol_type): unit
        for unit in scan_result.discovered_units
    }
    for block in blocks:
        if not isinstance(block, dict) or id(block) in incomplete_ids:
            continue
        code = block.get("code")
        if not isinstance(code, dict):
            continue
        # Only blocks already carrying line metadata need this mechanical
        # maintenance pass; otherwise every complete declared block would be
        # reopened merely because the scanner knows its line numbers.
        if "start_line" not in code and "end_line" not in code:
            continue
        key = (clean_string(code.get("path")), clean_string(code.get("symbol")), clean_string(code.get("kind")))
        if None in key:
            continue
        unit = discovered_by_key.get(key)
        if unit is None or code.get("start_line") != unit.start_line or code.get("end_line") != unit.end_line:
            issues.append(InspectIssue(issue_type=ISSUE_DRAFT, block=block))

    # New undeclared code is handled by Drift Gate before metadata inspection.
    # Inspector only receives new-code issues after a human approves them.
    return sort_inspect_issues_hierarchically(issues)


def get_incomplete_blocks(
    blueprint_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Return blocks that are missing required human fields."""

    blocks = blueprint_data.get("blocks", [])
    if not isinstance(blocks, list):
        return []

    incomplete: List[Dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        values = {
            "purpose": block.get("purpose"),
            "domain": block.get("domain"),
            "status": block.get("status"),
        }
        for field_name in REQUIRED_HUMAN_FIELDS:
            value = values.get(field_name)
            if value is None or (isinstance(value, str) and not value.strip()):
                incomplete.append(block)
                break
    return incomplete


def clean_string(value: Any) -> str | None:
    """Return a stripped string or None for blank values."""

    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def display_value(value: Any) -> str:
    """Render blank values consistently."""

    return clean_string(value) or "-"


def suggest_domain(block: Dict[str, Any]) -> str | None:
    """Suggest the first stable non-placeholder domain for one block."""

    from bpfw.integrations.inspector.suggestions.domain.engine import suggest_domains as catalog_suggest_domains

    suggestions = catalog_suggest_domains(block)
    if not suggestions:
        return None
    for suggestion in suggestions:
        normalized_suggestion = suggestion.strip().lower()
        if normalized_suggestion in {"", "-", "custom"}:
            continue
        return normalized_suggestion
    return None


def collect_existing_purposes(blueprint_data: Dict[str, Any]) -> tuple[str, ...]:
    """Collect existing declared purposes from blueprint blocks."""

    blocks = blueprint_data.get("blocks", [])
    if not isinstance(blocks, list):
        return ()
    values: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        purpose_value = clean_string(block.get("purpose"))
        if purpose_value is not None and purpose_value not in values:
            values.append(purpose_value)
    return tuple(values)


def suggest_lifecycle(_responsibility: Dict[str, Any]) -> str:
    """Suggest the default status for catalog mode."""

    return "active"


def apply_suggestions(block: Dict[str, Any]) -> None:
    """Apply stable suggestions before rendering one block."""

    if clean_string(block.get("domain")) is None:
        domain = suggest_domain(block)
        if domain is not None:
            block["domain"] = domain
    if clean_string(block.get("status")) is None:
        block["status"] = suggest_lifecycle(block)


def backfill_detected_docstring_from_source(project_root: Path, block: Dict[str, Any]) -> None:
    """Populate detected docstring from source when blueprint metadata lacks it."""

    detected = block.get("detected")
    if not isinstance(detected, dict):
        detected = {}
        block["detected"] = detected
    if clean_string(detected.get("docstring")) is not None:
        return

    location = block.get("code", {})
    if not isinstance(location, dict):
        return
    relative_path = clean_string(location.get("path"))
    symbol = clean_string(location.get("symbol"))
    symbol_type = clean_string(location.get("kind"))
    if relative_path is None or symbol is None or symbol_type is None:
        return

    source_path = project_root / relative_path
    if not source_path.exists():
        return
    try:
        module_ast = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return

    node_line = location.get("start_line")
    matching_node = _find_matching_symbol_node(
        module_ast=module_ast,
        symbol_type=symbol_type,
        target_name=symbol.split(".")[-1],
        node_line=node_line if isinstance(node_line, int) else None,
    )
    if matching_node is None:
        return

    docstring = ast.get_docstring(matching_node)
    if docstring:
        detected["docstring"] = docstring


def build_history_summary_lines(project_root: Path, block: Dict[str, Any], limit: int = 5) -> list[str]:
    """Build recent semantic/physical history lines for the current block."""

    try:
        from bpfw.core.history.ledger import HistoryLedger
        target = clean_string(block.get("uid")) or clean_string(block.get("id"))
        if target is None:
            return ["  -  No stable block identity yet."]
        events = HistoryLedger(project_root).query(target, limit=limit)
    except Exception as error:
        return [f"  -  History unavailable: {error}"]
    if not events:
        return ["  -  No recorded history yet."]
    lines: list[str] = []
    for event in events:
        timestamp = str(event.get("timestamp") or "-").replace("T", " ")[:19]
        event_type = str(event.get("event_type") or "-")
        reason = event.get("reason")
        if isinstance(reason, dict):
            reason = reason.get("summary") or reason.get("details")
        suffix = f" · {reason}" if isinstance(reason, str) and reason else ""
        lines.append(f"  {timestamp}  {event_type}{suffix}")
    return lines


def build_artifact_summary_lines(project_root: Path, block: Dict[str, Any], artifact_index: int | None = None) -> list[str]:
    """Build a compact list of physical artifacts attached to a logical block."""

    artifacts = block_artifacts(block)
    if not artifacts:
        return ["  -  No artifacts declared."]
    resolver = ArtifactResolver(project_root)
    primary = choose_primary_artifact(block)
    selected = artifacts[artifact_index] if isinstance(artifact_index, int) and 0 <= artifact_index < len(artifacts) else primary
    lines: list[str] = []
    for index, artifact in enumerate(artifacts, 1):
        resolved = resolver.resolve(artifact)
        marker = "*" if selected is not None and artifact == selected else " "
        kind = (resolved.kind or resolved.type or "artifact").upper()
        label = clean_string(artifact.get("id")) or clean_string(artifact.get("symbol")) or Path(resolved.path).name
        span = f"L{resolved.start_line}-{resolved.end_line}" if resolved.resolved else "unresolved"
        lines.append(f" {marker} [{index}] {resolved.type.upper():<7} {label} · {resolved.path} · {kind} · {span}")
    return lines


def build_code_lines(
    project_root: Path,
    block: Dict[str, Any],
    project_blocks: list[dict[str, Any]] | None = None,
    artifact_index: int | None = None,
) -> list[str]:
    """Build numbered source lines for the block's primary physical artifact.

    Alpha.13 keeps the old Python hierarchical preview when a legacy Python code
    block is inspected, but v2 artifacts are resolved through the parser-neutral
    ArtifactResolver so Go, prompts, config, specs, and skills can use the same UI.
    """

    artifacts = block_artifacts(block)
    primary = choose_primary_artifact(block)
    if isinstance(artifact_index, int) and 0 <= artifact_index < len(artifacts):
        primary = artifacts[artifact_index]
    if primary is None:
        return ["  -  No source artifact detected."]

    # Preserve the mature hierarchical Python experience for legacy code blocks.
    explicit_artifacts = block.get("artifacts")
    if not explicit_artifacts and str(primary.get("type", "code")) == "code":
        language = clean_string(primary.get("language"))
        path = clean_string(primary.get("path")) or ""
        if language in {None, "python"} and path.endswith(".py"):
            folded_preview = _HierarchicalCodePreviewRenderer(
                project_root=project_root, block=block, project_blocks=project_blocks
            ).render()
            if folded_preview is not None:
                return folded_preview

    resolver = ArtifactResolver(project_root)
    resolved = resolver.resolve(primary)
    if not resolved.path:
        return ["  -  No source location detected."]
    source_path = project_root / resolved.path
    if not source_path.exists():
        return [f"  -  Source file not found: {resolved.path}"]
    if not resolved.resolved:
        detail = f": {resolved.message}" if resolved.message else ""
        return [f"  -  Artifact location unresolved{detail}"]
    try:
        source_text = source_path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return [f"  -  Cannot read artifact: {error}"]
    source_lines = source_text.splitlines()
    start_line = resolved.start_line or 1
    end_line = resolved.end_line or start_line
    displayed_start_line = _find_display_start_line(source_lines=source_lines, start_line=start_line)
    displayed_end_line = _find_display_end_line(source_lines=source_lines, end_line=end_line)
    selected_lines = source_lines[max(displayed_start_line - 1, 0):displayed_end_line]
    width = max(len(str(displayed_end_line)), 3)
    rendered = [f"{line_number:>{width}}  {line}" for line_number, line in enumerate(selected_lines, start=displayed_start_line)]

    stored_start = primary.get("start_line")
    stored_end = primary.get("end_line")
    if resolved.resolution == "FALLBACK":
        rendered.insert(0, "  -  Location drift: using stored lines because symbol location was not resolved.")
    elif isinstance(stored_start, int) and isinstance(stored_end, int) and (stored_start, stored_end) != (start_line, end_line):
        rendered.insert(0, f"  -  Location drift: stored {stored_start}-{stored_end}, source {start_line}-{end_line} (using source).")
    if resolved.detected.get("variables"):
        rendered.insert(0, "  -  Prompt variables: " + ", ".join(resolved.detected["variables"]))
    return rendered


def resolve_current_block_location(project_root: Path, block: Dict[str, Any]) -> tuple[int, int] | None:
    """Resolve the current primary source location through ArtifactResolver."""

    primary = choose_primary_artifact(block)
    if primary is None:
        return None
    resolved = ArtifactResolver(project_root).resolve(primary)
    if not resolved.resolved:
        return None
    return int(resolved.start_line), int(resolved.end_line)


def sync_block_code_location(project_root: Path, block: Dict[str, Any]) -> bool:
    """Sync legacy ``code`` lines only.

    Explicit v2 artifact spans are deliberately derived into BPFW state/history,
    not written back into authority on every movement.
    """
    if isinstance(block.get("artifacts"), list) and block.get("artifacts"):
        return False
    location = block.get("code", {})
    if not isinstance(location, dict):
        return False
    artifact = {
        "id": "legacy_code", "type": "code", "path": location.get("path"),
        "language": location.get("language"), "symbol": location.get("symbol"),
        "kind": location.get("kind"), "start_line": location.get("start_line"),
        "end_line": location.get("end_line"),
    }
    resolved = ArtifactResolver(project_root).resolve(artifact)
    if not resolved.resolved:
        return False
    resolved_start_line, resolved_end_line = int(resolved.start_line), int(resolved.end_line)
    if location.get("start_line") == resolved_start_line and location.get("end_line") == resolved_end_line:
        return False
    location["start_line"] = resolved_start_line
    location["end_line"] = resolved_end_line
    return True


def _has_location_drift(block: Dict[str, Any], resolved_start_line: int, resolved_end_line: int) -> bool:
    """Return whether resolved source lines differ from stored lines."""
    location = block.get("code", {})
    if not isinstance(location, dict):
        return False
    return (
        location.get("start_line") != resolved_start_line
        or location.get("end_line") != resolved_end_line
    )


def _resolve_snippet_start_line(
    source_text: str,
    location: dict[str, Any],
    fallback_start_line: int,
) -> int:
    """Return decorator-aware block start line when source node can be resolved."""

    symbol = clean_string(location.get("symbol"))
    symbol_type = clean_string(location.get("kind"))
    if symbol is None or symbol_type is None:
        return fallback_start_line

    try:
        module_ast = ast.parse(source_text)
    except SyntaxError:
        return fallback_start_line

    target_name = symbol.split(".")[-1]
    node_line = location.get("start_line")
    matching_node = _find_matching_symbol_node(
        module_ast=module_ast,
        symbol_type=symbol_type,
        target_name=target_name,
        node_line=node_line if isinstance(node_line, int) else None,
    )
    if matching_node is None:
        return fallback_start_line

    decorators = getattr(matching_node, "decorator_list", None)
    if decorators:
        return min(decorator.lineno for decorator in decorators)

    resolved_start_line = getattr(matching_node, "lineno", None)
    if isinstance(resolved_start_line, int):
        return resolved_start_line
    return fallback_start_line


def _find_matching_symbol_node(
    module_ast: ast.Module,
    symbol_type: str,
    target_name: str,
    node_line: int | None,
) -> ast.AST | None:
    """Find class/function node matching the located symbol."""

    normalized_type = symbol_type.lower()
    function_nodes: tuple[type[ast.AST], ...]
    if hasattr(ast, "AsyncFunctionDef"):
        function_nodes = (ast.FunctionDef, ast.AsyncFunctionDef)
    else:
        function_nodes = (ast.FunctionDef,)

    candidate_types: tuple[type[ast.AST], ...]
    if normalized_type == "class":
        candidate_types = (ast.ClassDef,)
    elif normalized_type in {"function", "method"}:
        candidate_types = function_nodes
    else:
        candidate_types = (ast.ClassDef, *function_nodes)

    for node in ast.walk(module_ast):
        if not isinstance(node, candidate_types):
            continue
        name = getattr(node, "name", None)
        if name != target_name:
            continue
        if node_line is not None and getattr(node, "lineno", None) != node_line:
            continue
        return node

    # Fallback when line numbers drift but symbol remains unique.
    if node_line is None:
        return None
    for node in ast.walk(module_ast):
        if not isinstance(node, candidate_types):
            continue
        if getattr(node, "name", None) == target_name:
            return node
    return None


def _find_display_start_line(source_lines: list[str], start_line: int) -> int:
    """Include contiguous blank lines before the block."""

    displayed_start_line = max(start_line, 1)
    while displayed_start_line > 1:
        previous_line = source_lines[displayed_start_line - 2]
        if previous_line.strip():
            break
        displayed_start_line -= 1
    return displayed_start_line


def _find_display_end_line(
    source_lines: list[str],
    end_line: int,
) -> int:
    """Include contiguous blank lines after the block."""

    displayed_end_line = min(end_line, len(source_lines))
    while displayed_end_line < len(source_lines):
        next_line = source_lines[displayed_end_line]
        if next_line.strip():
            break
        displayed_end_line += 1
    return displayed_end_line


def build_authority_lines(block: Dict[str, Any]) -> list[str]:
    """Build authority field lines for display."""

    return [
        f"  id              {display_value(block.get('id'))}",
        f"  purpose         {display_value(block.get('purpose'))}",
        f"  domain          {display_value(block.get('domain'))}",
        f"  status          {display_value(block.get('status'))}",
        f"  observations    {display_value(block.get('notes'))}",
    ]


def build_suggestion_lines(block: Dict[str, Any]) -> list[str]:
    """Build stable suggestion lines for display."""

    return [
        f"  domain     {display_value(suggest_domain(block))}",
        f"  status     {suggest_lifecycle(block)}",
    ]


def build_nested_snippet_lines(block: Dict[str, Any]) -> list[str]:
    """Build direct nested block lines for display."""

    detected = block.get("detected")
    if not isinstance(detected, dict):
        return []

    nested_symbols: list[str] = []
    for field_name in ("methods", "functions"):
        values = detected.get(field_name)
        if not isinstance(values, list):
            continue
        for value in values:
            symbol = clean_string(value)
            if symbol is not None and symbol not in nested_symbols:
                nested_symbols.append(symbol)

    return [f"  {symbol}" for symbol in nested_symbols]


def build_hierarchy_lines(block: Dict[str, Any]) -> list[str]:
    """Build contained-to-container hierarchy lines for inspector display."""

    location = block.get("code", {})
    if not isinstance(location, dict):
        return ["  -  No hierarchy detected."]

    path_value = clean_string(location.get("path"))
    module_value = clean_string(location.get("module"))
    symbol_value = clean_string(location.get("symbol"))
    symbol_type_value = clean_string(location.get("kind")) or "symbol"

    hierarchy_lines: list[str] = []

    if symbol_value:
        symbol_parts = symbol_value.split(".")
        hierarchy_lines.append(f"  leaf: {symbol_parts[-1]} ({symbol_type_value})")
        for symbol_name in reversed(symbol_parts[:-1]):
            hierarchy_lines.append(f"  parent symbol: {symbol_name}")

    if module_value:
        hierarchy_lines.append(f"  module: {module_value}")
    if path_value:
        hierarchy_lines.append(f"  file: {path_value}")
        path_parts = [part for part in path_value.replace('\\', '/').split('/') if part]
        folder_parts = path_parts[:-1]
        for folder_name in reversed(folder_parts):
            hierarchy_lines.append(f"  folder: {folder_name}")

    nested_lines = build_nested_snippet_lines(block)
    if nested_lines:
        hierarchy_lines.append("  children:")
        hierarchy_lines.extend(nested_lines)

    if not hierarchy_lines:
        return ["  -  No hierarchy detected."]
    return hierarchy_lines


def apply_automatic_authority_fields(blueprint_data: Dict[str, Any]) -> None:
    """Derive authority fields that do not require interactive review.

    Alpha.13 also assigns stable UIDs to historical entities.  UIDs are identity,
    while human-facing ids remain renameable semantic labels.
    """

    from bpfw.core.history.identity import ensure_authority_uids
    ensure_authority_uids(blueprint_data)

    blocks = blueprint_data.get("blocks", [])
    if not isinstance(blocks, list):
        return

    grouped_blocks: dict[str, list[dict[str, Any]]] = {}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        purpose = clean_string(block.get("purpose"))
        if purpose is None:
            continue
        group = to_snake_case(purpose)
        uniqueness = block.get("uniqueness", {})
        if not uniqueness:
            uniqueness = block.setdefault("uniqueness", {})
        if uniqueness.get("group") is None:
            uniqueness["group"] = group
        grouped_blocks.setdefault(group, []).append(block)

    for grouped in grouped_blocks.values():
        active = [item for item in grouped if item.get("status") == "active"]
        if len(active) > 1:
            active_ids = [str(item.get("id")) for item in active if item.get("id")]
            for item in active:
                uniqueness = item.get("uniqueness", {})
                if not uniqueness:
                    uniqueness = item.setdefault("uniqueness", {})
                duplicates = uniqueness.setdefault("suspected_duplicates", [])
                for identifier in active_ids:
                    if identifier != str(item.get("id")) and identifier not in duplicates:
                        duplicates.append(identifier)

    blueprint_data["blocks"] = [block for block in blocks if isinstance(block, dict)]


def save_blueprint(
    blueprint_path: Path,
    blueprint_data: Dict[str, Any],
    authority_document: Any | None = None,
) -> None:
    """Save blueprint data to authority using the appropriate method.

    Args:
        blueprint_path: Path to the blueprint index file.
        blueprint_data: Unified blueprint data with blocks.
        authority_document: Optional AuthorityDocument from load_inspect_session.
    """

    apply_automatic_authority_fields(blueprint_data)
    try:
        from bpfw.core.automation.profiles import strip_ephemeral
        blueprint_data = strip_ephemeral(blueprint_data)
    except Exception:
        pass

    project_root = blueprint_path.parent.parent
    from bpfw.core.authority.sqlite.migration import active_backend
    if active_backend(project_root) == 'sqlite':
        from bpfw.core.blueprint_engine.engine import BlueprintEngine
        BlueprintEngine(project_root).replace_authority_document(
            blueprint_data, reason='inspector.save_blueprint',
            expected_revision=getattr(authority_document, 'sqlite_revision', None))
        return

    # Use sharded authority path when layout declares it.
    if _has_sharded_authority_layout(blueprint_data):
        from bpfw.core.authority import AuthorityRepository

        repository = AuthorityRepository(project_root)

        if authority_document is not None:
            authority_document.blueprint_data = blueprint_data
            repository.save(authority_document)
        else:
            document = repository.load()
            document.blueprint_data = blueprint_data
            repository.save(document)
    else:
        # Simple blueprint.yaml file - save directly using writer
        from bpfw.core.catalog.writer import write_blueprint
        write_blueprint(blueprint_path, blueprint_data)
