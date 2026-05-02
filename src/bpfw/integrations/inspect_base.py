"""Shared inspect behavior for BPFW catalog completion."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import yaml

from bpfw.catalog.access_control import ensure_blueprint_can_be_written
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
REQUIRED_HUMAN_FIELDS = ("intent", "canonical_name", "owner_layer", "lifecycle")
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
        "canonical_name": unit.symbol,
        "owner_layer": None,
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


def suggest_owner_layer(responsibility: Dict[str, Any]) -> str | None:
    """Suggest owner_layer from the code path."""

    location = responsibility.get("location", {})
    if not isinstance(location, dict):
        return None

    path = clean_string(location.get("path"))
    if path is None:
        return None

    for marker in ("src/bpfw/", "bpfw/"):
        if marker in path:
            remainder = path.split(marker, 1)[1]
            layer = remainder.split("/", 1)[0]
            if layer:
                return layer
    return None


def suggest_lifecycle(_responsibility: Dict[str, Any]) -> str:
    """Suggest the default lifecycle for catalog mode."""

    return "active"


def apply_suggestions(responsibility: Dict[str, Any]) -> None:
    """Apply deterministic suggestions before rendering one responsibility."""

    if clean_string(responsibility.get("owner_layer")) is None:
        owner_layer = suggest_owner_layer(responsibility)
        if owner_layer is not None:
            responsibility["owner_layer"] = owner_layer
    if clean_string(responsibility.get("lifecycle")) is None:
        responsibility["lifecycle"] = suggest_lifecycle(responsibility)


def validate_ready_to_accept(responsibility: Dict[str, Any]) -> list[str]:
    """Return required fields still missing before accepting."""

    missing_fields = []
    for field_name in REQUIRED_HUMAN_FIELDS:
        if clean_string(responsibility.get(field_name)) is None:
            missing_fields.append(field_name)
    return missing_fields


def build_code_lines(project_root: Path, responsibility: Dict[str, Any]) -> list[str]:
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

    source_lines = source_path.read_text(encoding="utf-8").splitlines()
    selected_lines = source_lines[max(start_line - 1, 0):end_line]
    line_number_width = max(len(str(end_line)), 3)
    return [
        f"{line_number:>{line_number_width}}  {line}"
        for line_number, line in enumerate(selected_lines, start=start_line)
    ]


def build_authority_lines(responsibility: Dict[str, Any]) -> list[str]:
    """Build authority field lines for display."""

    return [
        f"  id              {display_value(responsibility.get('id'))}",
        f"  intent          {display_value(responsibility.get('intent'))}",
        f"  canonical_name  {display_value(responsibility.get('canonical_name'))}",
        f"  owner_layer     {display_value(responsibility.get('owner_layer'))}",
        f"  lifecycle       {display_value(responsibility.get('lifecycle'))}",
        f"  notes           {display_value(responsibility.get('notes'))}",
    ]


def build_suggestion_lines(responsibility: Dict[str, Any]) -> list[str]:
    """Build deterministic suggestion lines for display."""

    return [
        f"  owner_layer  {display_value(suggest_owner_layer(responsibility))}",
        f"  lifecycle    {suggest_lifecycle(responsibility)}",
    ]


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
