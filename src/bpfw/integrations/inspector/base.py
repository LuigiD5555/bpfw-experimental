"""Shared inspector behavior for BPFW catalog completion."""
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, TYPE_CHECKING

from bpfw.catalog.access_control import ensure_blueprint_can_be_written
from bpfw.catalog.loader import BlueprintLoader
from bpfw.catalog.models import (
    AUTHORITY_STATE_INVALID,
    AUTHORITY_STATE_MISSING,
    DiscoveredCodeUnit,
)
from bpfw.catalog.models import ScanResult
from bpfw.catalog.verify import run_verify, scan_project_from_blueprint
from bpfw.core.errors import BlueprintLockedError
from bpfw.reports.finding import Finding
from bpfw.shared.text import to_snake_case
from bpfw.core.profiling import RuntimeProfiler

if TYPE_CHECKING:
    from bpfw.reports.verify_report import VerificationReport

_profiler = RuntimeProfiler()

ALLOWED_STATUSES = ("active", "experimental", "legacy", "deprecated")
REQUIRED_HUMAN_FIELDS = ("purpose", "name", "domain", "status")
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
    discovered_count: int = 0
    undeclared_count: int = 0
    missing_declared_count: int = 0
    drift_findings: list[Finding] | None = None
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
            message="No blueprint found. Run bpfw init first.",
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
            message="Blueprint is invalid. Fix bpfw/blueprint.yaml before running inspect.",
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
            message="Blueprint is locked. Run bpfw unlock before editing.",
            exit_code=1,
        )

    with _profiler.measure("inspector.load_authority_document"):
        # Load authority document only for sharded authority.
        blueprint_for_authority_check = blueprint_data if isinstance(blueprint_data, dict) else load_result.data
        authority_document = None

        if _has_sharded_authority_layout(blueprint_for_authority_check):
            repository = AuthorityRepository(resolved_root)
            authority_document = repository.load()

            # Always use canonical sharded authority data from repository.
            blueprint_data = authority_document.blueprint_data
        elif blueprint_data is None:
            # Simple blueprint.yaml - use data from loader
            blueprint_data = load_result.data

    with _profiler.measure("inspector.scan_project"):
        # Only scan if we don't have a precomputed result
        if scan_result is None:
            scan_result = scan_project_from_blueprint(
                project_root=resolved_root,
                blueprint_data=blueprint_data,
            )

    with _profiler.measure("inspector.run_verify"):
        # Only run verify if we don't have a precomputed report
        if report is None:
            report, _exit_code = run_verify(
                project_root=resolved_root,
                precomputed_scan_result=scan_result,
            )

    drift_findings = [
        finding
        for finding in report.findings
        if finding.code in {"UNDECLARED_CODE", "MISSING_DECLARED_CODE"}
    ]
    
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
        discovered_count=report.discovered_count,
        undeclared_count=report.undeclared_count,
        missing_declared_count=report.missing_declared_count,
        drift_findings=drift_findings,
    )


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


def _discovered_key(unit: DiscoveredCodeUnit) -> tuple[str, str, str]:
    """Return the path, symbol, and kind key for discovered code."""

    return unit.path, unit.symbol, unit.symbol_type


def build_new_detected_responsibility(unit: DiscoveredCodeUnit) -> Dict[str, Any]:
    """Build a pending block from one newly detected code unit."""

    block = {
        "id": to_snake_case(unit.symbol),
        "purpose": None,
        "name": unit.symbol,
        "domain": None,
        "status": "active",
        "code": {
            "path": unit.path,
            "module": unit.module,
            "symbol": unit.symbol,
            "kind": unit.symbol_type,
            "start_line": unit.start_line,
            "end_line": unit.end_line,
        },
        "detected": {
            "qualified_name": unit.qualified_name,
            "kind": unit.symbol_type,
            "methods": unit.methods,
            "functions": unit.functions,
            "imports": unit.imports,
            "decorators": unit.decorators,
            "docstring": unit.docstring,
            "signature": unit.signature,
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

    issues = [
        InspectIssue(issue_type=ISSUE_DRAFT, block=block)
        for block in incomplete
    ]

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

    for unit in scan_result.discovered_units:
        if _discovered_key(unit) in declared_keys:
            continue
        issues.append(
            InspectIssue(
                issue_type=ISSUE_NEW_DETECTED,
                block=build_new_detected_responsibility(unit),
                add_on_accept=True,
            )
        )

    return issues


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
            "name": block.get("name"),
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
    """Suggest the first deterministic non-placeholder domain for one block.

    Args:
        block: Block dictionary.

    Returns:
        First domain suggestion when it is usable, otherwise ``None``.
    """

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
    """Apply deterministic suggestions before rendering one block."""

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


def build_code_lines(
    project_root: Path,
    block: Dict[str, Any],
) -> list[str]:
    """Build numbered source lines for the block code location."""

    location = block.get("code", {})
    if not isinstance(location, dict):
        return ["  -  No source location detected."]

    relative_path = clean_string(location.get("path"))
    start_line = location.get("start_line")
    end_line = location.get("end_line")
    if relative_path is None or not isinstance(start_line, int) or not isinstance(end_line, int):
        return ["  -  No source location detected."]

    source_path = project_root / relative_path
    if not source_path.exists():
        return [f"  -  Source file not found: {relative_path}"]

    source_text = source_path.read_text(encoding="utf-8")
    source_lines = source_text.splitlines()
    snippet_start_line = _resolve_snippet_start_line(
        source_text=source_text,
        location=location,
        fallback_start_line=start_line,
    )
    displayed_start_line = _find_display_start_line(
        source_lines=source_lines,
        start_line=snippet_start_line,
    )
    displayed_end_line = _find_display_end_line(
        source_lines=source_lines,
        end_line=end_line,
    )
    selected_lines = source_lines[max(displayed_start_line - 1, 0):displayed_end_line]
    line_number_width = max(len(str(displayed_end_line)), 3)
    return [
        f"{line_number:>{line_number_width}}  {line}"
        for line_number, line in enumerate(selected_lines, start=displayed_start_line)
    ]


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
        f"  purpose         {display_value(block.get("purpose"))}",
        f"  name            {display_value(block.get('name'))}",
        f"  domain          {display_value(block.get('domain'))}",
        f"  status          {display_value(block.get("status"))}",
        f"  observations    {display_value(block.get('notes'))}",
    ]


def build_suggestion_lines(block: Dict[str, Any]) -> list[str]:
    """Build deterministic suggestion lines for display."""

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
    """Derive authority fields that do not require interactive review."""

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

    project_root = blueprint_path.parent.parent

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
        from bpfw.catalog.writer import write_blueprint
        write_blueprint(blueprint_path, blueprint_data)
