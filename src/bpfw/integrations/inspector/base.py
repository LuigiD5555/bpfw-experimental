"""Shared inspector behavior for BPFW catalog completion."""
import ast
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Dict, List

import yaml

from bpfw.catalog.access_control import ensure_blueprint_can_be_written
from bpfw.catalog.domain_suggestions import BROAD_FOLDER_TOKENS
from bpfw.catalog.domain_suggestions import suggest_domains as suggest_domain_objects
from bpfw.catalog.loader import BlueprintLoader
from bpfw.catalog.models import (
    AUTHORITY_STATE_INVALID,
    AUTHORITY_STATE_MISSING,
    DiscoveredCodeUnit,
)
from bpfw.catalog.scanner import scan_python_project
from bpfw.catalog.schema import (
    get_blocks,
    get_code,
    get_kind,
    get_purpose,
    get_status,
    get_uniqueness,
    set_blocks,
)
from bpfw.catalog.verify import _read_ignored_paths, _read_source_roots
from bpfw.catalog.verify import run_verify
from bpfw.core.errors import BlueprintLockedError
from bpfw.reports.finding import Finding
from bpfw.shared.text import to_snake_case

ALLOWED_LIFECYCLES = ("active", "experimental", "legacy", "deprecated")
REQUIRED_HUMAN_FIELDS = ("purpose", "name", "domain", "status")
ISSUE_DRAFT = "draft"
ISSUE_NEW_DETECTED = "new_detected"


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


def load_inspect_session(project_root: Path) -> InspectLoadResult:
    """Load blueprint data and return the inspect work set."""

    resolved_root = project_root.resolve()
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

    blueprint_data = load_result.data
    report, _exit_code = run_verify(project_root=resolved_root)
    drift_findings = [
        finding
        for finding in report.findings
        if finding.code in {"UNDECLARED_CODE", "MISSING_DECLARED_CODE"}
    ]
    incomplete = get_incomplete_responsibilities(blueprint_data)
    issues = build_inspect_issues(
        project_root=resolved_root,
        blueprint_data=blueprint_data,
        incomplete=incomplete,
    )
    return InspectLoadResult(
        project_root=resolved_root,
        blueprint_path=Path(load_result.path),
        blueprint_data=blueprint_data,
        incomplete=incomplete,
        issues=issues,
        authority_state=load_result.state,
        discovered_count=report.discovered_count,
        undeclared_count=report.undeclared_count,
        missing_declared_count=report.missing_declared_count,
        drift_findings=drift_findings,
    )


def _responsibility_key(block: Dict[str, Any]) -> tuple[str, str, str] | None:
    """Return the path, symbol, and kind key for a block."""

    location = get_code(block)
    if not isinstance(location, dict):
        return None

    path = clean_string(location.get("path"))
    symbol = clean_string(location.get("symbol"))
    symbol_type = clean_string(get_kind(location))
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
    project_root: Path,
    blueprint_data: Dict[str, Any],
    incomplete: List[Dict[str, Any]],
) -> list[InspectIssue]:
    """Build ordered inspect issues from incomplete and newly detected code."""

    issues = [
        InspectIssue(issue_type=ISSUE_DRAFT, block=block)
        for block in incomplete
    ]

    source_roots = _read_source_roots(blueprint_data)
    ignored_paths = _read_ignored_paths(blueprint_data)
    scan_result = scan_python_project(
        project_root=project_root,
        source_roots=source_roots,
        ignored_paths=ignored_paths,
    )

    blocks = get_blocks(blueprint_data)
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


def get_incomplete_responsibilities(
    blueprint_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Return blocks that are missing required human fields."""

    blocks = get_blocks(blueprint_data)
    if not isinstance(blocks, list):
        return []

    incomplete: List[Dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        values = {
            "purpose": get_purpose(block),
            "name": block.get("name"),
            "domain": block.get("domain"),
            "status": get_status(block),
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
    """Suggest the strongest deterministic domain for one block."""

    suggestions = suggest_domains(block)
    if not suggestions:
        return None
    return suggestions[0]


def suggest_domains(block: Dict[str, Any], project_blocks: List[Dict[str, Any]] | None = None) -> List[str]:
    """Suggest inspector domains using catalog deterministic engine plus adapter rules."""

    location = get_code(block)
    symbol_based = None
    module_based = None
    file_based = None
    path_folders: List[str] = []
    if isinstance(location, dict):
        symbol = clean_string(location.get("symbol"))
        if symbol:
            symbol_tokens = []
            current = ""
            for character in symbol:
                if character == "_":
                    if current:
                        symbol_tokens.append(current.lower())
                    current = ""
                    continue
                if character.isupper() and current:
                    symbol_tokens.append(current.lower())
                    current = character
                else:
                    current += character
            if current:
                symbol_tokens.append(current.lower())
            filtered = [token for token in symbol_tokens if token not in {"service", "manager", "handler", "helper", "run", "session", "text"}]
            if filtered:
                symbol_based = filtered[0]

        module = clean_string(location.get("module"))
        if module:
            parts = [part.strip().lower() for part in module.split(".") if part.strip()]
            parts = [part for part in parts if part not in {"src", "bpfw", "tests", "test", "__init__"}]
            if parts:
                module_based = parts[-1]

        path = clean_string(location.get("path"))
        if path:
            normalized_path = path.replace("\\", "/")
            path_parts = normalized_path.split("/")
            file_name = path_parts[-1]
            file_based = file_name.removesuffix(".py").lower()
            if file_based in {"src", "bpfw", "tests", "test", "__init__"}:
                file_based = None
            for part in path_parts[:-1]:
                normalized = part.strip().lower()
                if (
                    normalized
                    and normalized not in {"src", "bpfw", "tests", "test", "__init__"}
                    and normalized not in BROAD_FOLDER_TOKENS
                    and normalized not in path_folders
                ):
                    path_folders.append(normalized)

    blended_candidates = [suggestion.text for suggestion in suggest_domain_objects(block)]
    ordered: List[str] = []
    for candidate in path_folders:
        if candidate not in ordered:
            ordered.append(candidate)
    for candidate in blended_candidates:
        if candidate not in ordered:
            ordered.append(candidate)
    for candidate in [file_based, module_based, symbol_based]:
        if candidate is not None and candidate not in ordered:
            ordered.append(candidate)
    historical_domains = _historical_domains_for_path(block=block, project_blocks=project_blocks or [])
    for candidate in historical_domains:
        if candidate not in ordered:
            ordered.append(candidate)

    clean: List[str] = []
    for candidate in ordered:
        normalized = candidate.strip().lower().replace("-", "_")
        if not normalized or normalized in {"src", "bpfw", "tests", "test", "__init__"}:
            continue
        if normalized not in clean:
            clean.append(normalized)
    fallback_tokens = ("core", "general", "shared", "misc", "system")
    historical_set = set(historical_domains)
    historical_in_clean = [domain for domain in historical_domains if domain in clean]
    if historical_in_clean:
        clean = [domain for domain in clean if domain not in historical_set]
        for token in fallback_tokens:
            if len(clean) >= 4:
                break
            if token not in clean:
                clean.append(token)
        insertion_index = min(4, len(clean))
        for offset, historical_domain in enumerate(historical_in_clean):
            clean.insert(insertion_index + offset, historical_domain)
    if len(clean) < 5:
        for token in fallback_tokens:
            if token not in clean:
                clean.append(token)
            if len(clean) >= 5:
                break
    return clean[:5]


def _historical_domains_for_path(
    block: Dict[str, Any],
    project_blocks: List[Dict[str, Any]],
) -> List[str]:
    """Return previously used domains for blocks with the same code path."""

    current_path = _block_path(block)
    if current_path is None:
        return []

    current_id = clean_string(block.get("id"))
    path_tokens = set(_path_tokens(current_path))
    domain_scores: dict[str, int] = {}
    for project_block in project_blocks:
        if project_block is block:
            continue
        if current_id is not None and clean_string(project_block.get("id")) == current_id:
            continue
        if _block_path(project_block) != current_path:
            continue
        domain_value = clean_string(project_block.get("domain"))
        if domain_value is None:
            continue
        normalized_domain = domain_value.lower().replace("-", "_")
        domain_tokens = set(_path_tokens(normalized_domain))
        domain_scores[normalized_domain] = max(
            domain_scores.get(normalized_domain, 0),
            len(path_tokens & domain_tokens),
        )

    ranked_domains = sorted(
        domain_scores,
        key=lambda domain: (-domain_scores[domain], domain),
    )
    return ranked_domains


def _block_path(block: Dict[str, Any]) -> str | None:
    """Return the normalized code path for a block."""

    location = get_code(block)
    if not isinstance(location, dict):
        return None
    path = clean_string(location.get("path"))
    if path is None:
        return None
    return path.replace("\\", "/").lower()


def _path_tokens(value: str) -> List[str]:
    """Tokenize path-like text into lowercase words."""

    return [token for token in re.split(r"[^a-zA-Z0-9]+", value.lower()) if token]


def collect_existing_intents(blueprint_data: Dict[str, Any]) -> tuple[str, ...]:
    """Collect existing declared purposes from blueprint blocks."""

    blocks = get_blocks(blueprint_data)
    if not isinstance(blocks, list):
        return ()
    values: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        purpose_value = clean_string(get_purpose(block))
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
    if clean_string(get_status(block)) is None:
        block["status"] = suggest_lifecycle(block)


def backfill_detected_docstring_from_source(project_root: Path, block: Dict[str, Any]) -> None:
    """Populate detected docstring from source when blueprint metadata lacks it."""

    detected = block.get("detected")
    if not isinstance(detected, dict):
        detected = {}
        block["detected"] = detected
    if clean_string(detected.get("docstring")) is not None:
        return

    location = get_code(block)
    if not isinstance(location, dict):
        return
    relative_path = clean_string(location.get("path"))
    symbol = clean_string(location.get("symbol"))
    symbol_type = clean_string(get_kind(location))
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

    location = get_code(block)
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
    symbol_type = clean_string(get_kind(location))
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
        f"  purpose         {display_value(get_purpose(block))}",
        f"  name            {display_value(block.get('name'))}",
        f"  domain          {display_value(block.get('domain'))}",
        f"  status          {display_value(get_status(block))}",
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

    location = get_code(block)
    if not isinstance(location, dict):
        return ["  -  No hierarchy detected."]

    path_value = clean_string(location.get("path"))
    module_value = clean_string(location.get("module"))
    symbol_value = clean_string(location.get("symbol"))
    symbol_type_value = clean_string(get_kind(location)) or "symbol"

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

    blocks = get_blocks(blueprint_data)
    if not isinstance(blocks, list):
        return

    grouped_blocks: dict[str, list[dict[str, Any]]] = {}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        purpose = clean_string(get_purpose(block))
        if purpose is None:
            continue
        group = to_snake_case(purpose)
        uniqueness = get_uniqueness(block)
        if not uniqueness:
            uniqueness = block.setdefault("uniqueness", {})
        if uniqueness.get("group") is None:
            uniqueness["group"] = group
        grouped_blocks.setdefault(group, []).append(block)

    for grouped in grouped_blocks.values():
        active = [item for item in grouped if get_status(item) == "active"]
        if len(active) > 1:
            active_ids = [str(item.get("id")) for item in active if item.get("id")]
            for item in active:
                uniqueness = get_uniqueness(item)
                if not uniqueness:
                    uniqueness = item.setdefault("uniqueness", {})
                duplicates = uniqueness.setdefault("suspected_duplicates", [])
                for identifier in active_ids:
                    if identifier != str(item.get("id")) and identifier not in duplicates:
                        duplicates.append(identifier)

    set_blocks(blueprint_data, [block for block in blocks if isinstance(block, dict)])

def save_blueprint(
    blueprint_path: Path,
    blueprint_data: Dict[str, Any],
) -> None:
    """Save blueprint data to the YAML file."""

    apply_automatic_authority_fields(blueprint_data)
    rendered = yaml.dump(blueprint_data, sort_keys=False, allow_unicode=True)
    blueprint_path.write_text(rendered, encoding="utf-8")
