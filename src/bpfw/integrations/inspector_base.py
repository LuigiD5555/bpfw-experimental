"""Shared inspector behavior for BPFW catalog completion."""
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import yaml

from bpfw.catalog.access_control import ensure_blueprint_can_be_written
from bpfw.catalog.domain_suggestions import suggest_domains as suggest_domain_objects
from bpfw.catalog.loader import BlueprintLoader
from bpfw.catalog.models import (
    AUTHORITY_STATE_INVALID,
    AUTHORITY_STATE_MISSING,
    DiscoveredCodeUnit,
)
from bpfw.catalog.scanner import scan_python_project
from bpfw.catalog.verify import _read_ignored_paths, _read_source_roots
from bpfw.catalog.verify import run_verify
from bpfw.catalog.writer import to_snake_case
from bpfw.core.errors import BlueprintLockedError
from bpfw.reports.finding import Finding

ALLOWED_LIFECYCLES = ("active", "experimental", "legacy", "deprecated")
REQUIRED_HUMAN_FIELDS = ("intent", "name", "domain", "lifecycle")
ISSUE_DRAFT = "draft"
ISSUE_NEW_DETECTED = "new_detected"


@dataclass(slots=True)
class InspectIssue:
    """One responsibility-level item to review in inspect."""

    issue_type: str
    responsibility: Dict[str, Any]
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


def _responsibility_key(responsibility: Dict[str, Any]) -> tuple[str, str, str] | None:
    """Return the path, symbol, and type key for a responsibility."""

    location = responsibility.get("location")
    if not isinstance(location, dict):
        return None

    path = clean_string(location.get("path"))
    symbol = clean_string(location.get("symbol"))
    symbol_type = clean_string(location.get("symbol_type"))
    if path is None or symbol is None or symbol_type is None:
        return None
    return path, symbol, symbol_type


def _discovered_key(unit: DiscoveredCodeUnit) -> tuple[str, str, str]:
    """Return the path, symbol, and type key for discovered code."""

    return unit.path, unit.symbol, unit.symbol_type


def build_new_detected_responsibility(unit: DiscoveredCodeUnit) -> Dict[str, Any]:
    """Build a pending responsibility from one newly detected code unit."""

    return {
        "id": to_snake_case(unit.symbol),
        "intent": None,
        "name": unit.symbol,
        "domain": None,
        "lifecycle": "active",
        "location": {
            "path": unit.path,
            "module": unit.module,
            "symbol": unit.symbol,
            "symbol_type": unit.symbol_type,
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
        "related_code": [],
        "duplicate_policy": {
            "group": None,
            "allow_multiple_non_active": True,
            "forbidden_active_duplicates": True,
            "suspected_duplicates": [],
        },
        "replacement": {
            "replaces": None,
            "replaced_by": None,
            "reason": None,
        },
        "notes": None,
    }


def build_inspect_issues(
    project_root: Path,
    blueprint_data: Dict[str, Any],
    incomplete: List[Dict[str, Any]],
) -> list[InspectIssue]:
    """Build ordered inspect issues from incomplete and newly detected code."""

    issues = [
        InspectIssue(issue_type=ISSUE_DRAFT, responsibility=responsibility)
        for responsibility in incomplete
    ]

    source_roots = _read_source_roots(blueprint_data)
    ignored_paths = _read_ignored_paths(blueprint_data)
    scan_result = scan_python_project(
        project_root=project_root,
        source_roots=source_roots,
        ignored_paths=ignored_paths,
    )

    responsibilities = blueprint_data.get("responsibilities")
    if not isinstance(responsibilities, list):
        responsibilities = []

    declared_keys = {
        key
        for responsibility in responsibilities
        if isinstance(responsibility, dict)
        for key in [_responsibility_key(responsibility)]
        if key is not None
    }

    for unit in scan_result.discovered_units:
        if _discovered_key(unit) in declared_keys:
            continue
        issues.append(
            InspectIssue(
                issue_type=ISSUE_NEW_DETECTED,
                responsibility=build_new_detected_responsibility(unit),
                add_on_accept=True,
            )
        )

    return issues


def get_incomplete_responsibilities(
    blueprint_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Return responsibilities that are missing required human fields."""

    responsibilities = blueprint_data.get("responsibilities", [])
    if not isinstance(responsibilities, list):
        return []

    incomplete: List[Dict[str, Any]] = []
    for responsibility in responsibilities:
        if not isinstance(responsibility, dict):
            continue
        for field_name in REQUIRED_HUMAN_FIELDS:
            value = responsibility.get(field_name)
            if value is None or (isinstance(value, str) and not value.strip()):
                incomplete.append(responsibility)
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


def suggest_domain(responsibility: Dict[str, Any]) -> str | None:
    """Suggest the strongest deterministic domain for one responsibility."""

    suggestions = suggest_domains(responsibility)
    if not suggestions:
        return None
    return suggestions[0]


def suggest_domains(responsibility: Dict[str, Any]) -> List[str]:
    """Suggest deterministic domains in z/x/c/v source order."""

    location = responsibility.get("location")
    symbol_based = None
    module_based = None
    file_based = None
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
            file_name = normalized_path.split("/")[-1]
            file_based = file_name.removesuffix(".py").lower()
            if file_based in {"src", "bpfw", "tests", "test", "__init__"}:
                file_based = None

    blended_candidates = [suggestion.text for suggestion in suggest_domain_objects(responsibility)]
    ordered = [symbol_based, module_based, file_based]
    for candidate in blended_candidates:
        if candidate not in ordered:
            ordered.append(candidate)
        if len([item for item in ordered if item]) >= 4:
            break

    clean: List[str] = []
    for candidate in ordered:
        if not candidate:
            continue
        normalized = candidate.strip().lower().replace("-", "_")
        if not normalized or normalized in {"src", "bpfw", "tests", "test", "__init__"}:
            continue
        if normalized not in clean:
            clean.append(normalized)
    if len(clean) < 4:
        fallback_tokens = ("core", "general", "shared", "misc")
        for token in fallback_tokens:
            if token not in clean:
                clean.append(token)
            if len(clean) >= 4:
                break
    return clean[:4]


def collect_existing_intents(blueprint_data: Dict[str, Any]) -> tuple[str, ...]:
    """Collect existing declared intents from blueprint responsibilities."""

    responsibilities = blueprint_data.get("responsibilities")
    if not isinstance(responsibilities, list):
        return ()
    values: list[str] = []
    for responsibility in responsibilities:
        if not isinstance(responsibility, dict):
            continue
        intent_value = clean_string(responsibility.get("intent"))
        if intent_value is not None and intent_value not in values:
            values.append(intent_value)
    return tuple(values)


def suggest_lifecycle(_responsibility: Dict[str, Any]) -> str:
    """Suggest the default lifecycle for catalog mode."""

    return "active"


def apply_suggestions(responsibility: Dict[str, Any]) -> None:
    """Apply deterministic suggestions before rendering one responsibility."""

    if clean_string(responsibility.get("domain")) is None:
        domain = suggest_domain(responsibility)
        if domain is not None:
            responsibility["domain"] = domain
    if clean_string(responsibility.get("lifecycle")) is None:
        responsibility["lifecycle"] = suggest_lifecycle(responsibility)


def build_code_lines(
    project_root: Path,
    responsibility: Dict[str, Any],
) -> list[str]:
    """Build numbered source lines for the responsibility location."""

    location = responsibility.get("location", {})
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
    """Return decorator-aware snippet start line when source node can be resolved."""

    symbol = clean_string(location.get("symbol"))
    symbol_type = clean_string(location.get("symbol_type"))
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
    """Include contiguous blank lines before the snippet."""

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
    """Include contiguous blank lines after the snippet."""

    displayed_end_line = min(end_line, len(source_lines))
    while displayed_end_line < len(source_lines):
        next_line = source_lines[displayed_end_line]
        if next_line.strip():
            break
        displayed_end_line += 1
    return displayed_end_line


def build_authority_lines(responsibility: Dict[str, Any]) -> list[str]:
    """Build authority field lines for display."""

    return [
        f"  id              {display_value(responsibility.get('id'))}",
        f"  intent          {display_value(responsibility.get('intent'))}",
        f"  name            {display_value(responsibility.get('name'))}",
        f"  domain          {display_value(responsibility.get('domain'))}",
        f"  lifecycle       {display_value(responsibility.get('lifecycle'))}",
        f"  observations    {display_value(responsibility.get('notes'))}",
    ]


def build_suggestion_lines(responsibility: Dict[str, Any]) -> list[str]:
    """Build deterministic suggestion lines for display."""

    return [
        f"  domain     {display_value(suggest_domain(responsibility))}",
        f"  lifecycle  {suggest_lifecycle(responsibility)}",
    ]


def build_nested_snippet_lines(responsibility: Dict[str, Any]) -> list[str]:
    """Build direct nested snippet lines for display."""

    detected = responsibility.get("detected")
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


def apply_automatic_authority_fields(blueprint_data: Dict[str, Any]) -> None:
    """Derive authority fields that do not require interactive review."""

    responsibilities = blueprint_data.get("responsibilities", [])
    if not isinstance(responsibilities, list):
        return

    grouped_responsibilities: dict[str, list[dict[str, Any]]] = {}
    for responsibility in responsibilities:
        if not isinstance(responsibility, dict):
            continue
        intent = clean_string(responsibility.get("intent"))
        if intent is None:
            continue
        group = to_snake_case(intent)
        duplicate_policy = responsibility.setdefault("duplicate_policy", {})
        if duplicate_policy.get("group") is None:
            duplicate_policy["group"] = group
        grouped_responsibilities.setdefault(group, []).append(responsibility)

    for grouped in grouped_responsibilities.values():
        active = [item for item in grouped if item.get("lifecycle") == "active"]
        if len(active) > 1:
            active_ids = [str(item.get("id")) for item in active if item.get("id")]
            for item in active:
                duplicate_policy = item.setdefault("duplicate_policy", {})
                duplicates = duplicate_policy.setdefault("suspected_duplicates", [])
                for identifier in active_ids:
                    if identifier != str(item.get("id")) and identifier not in duplicates:
                        duplicates.append(identifier)


def save_blueprint(
    blueprint_path: Path,
    blueprint_data: Dict[str, Any],
) -> None:
    """Save blueprint data to the YAML file."""

    apply_automatic_authority_fields(blueprint_data)
    rendered = yaml.dump(blueprint_data, sort_keys=False, allow_unicode=True)
    blueprint_path.write_text(rendered, encoding="utf-8")
