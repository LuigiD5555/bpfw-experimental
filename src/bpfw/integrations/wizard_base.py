"""Shared wizard behavior for BPFW catalog completion."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import yaml

from bpfw.catalog.access_control import ensure_blueprint_can_be_written
from bpfw.catalog.loader import BlueprintLoader
from bpfw.catalog.models import (
    AUTHORITY_STATE_EMPTY,
    AUTHORITY_STATE_INVALID,
    AUTHORITY_STATE_MISSING,
)
from bpfw.catalog.writer import to_snake_case
from bpfw.core.errors import BlueprintLockedError

ALLOWED_LIFECYCLES = ("active", "experimental", "legacy", "deprecated")
REQUIRED_HUMAN_FIELDS = ("intent", "canonical_name", "owner_layer", "lifecycle")


@dataclass(slots=True)
class WizardLoadResult:
    """Loaded wizard state or a blocking message."""

    project_root: Path
    blueprint_path: Path | None
    blueprint_data: Dict[str, Any]
    incomplete: List[Dict[str, Any]]
    authority_state: str
    message: str | None = None
    exit_code: int = 0

    @property
    def blocked(self) -> bool:
        """Return True when the wizard cannot continue."""

        return self.exit_code != 0


def load_wizard_session(project_root: Path) -> WizardLoadResult:
    """Load blueprint data and return the wizard work set."""

    resolved_root = project_root.resolve()
    loader = BlueprintLoader(project_root=resolved_root)
    load_result = loader.load()

    if load_result.state == AUTHORITY_STATE_MISSING:
        return WizardLoadResult(
            project_root=resolved_root,
            blueprint_path=None,
            blueprint_data={},
            incomplete=[],
            authority_state=load_result.state,
            message="No blueprint found. Run bpfw init first.",
            exit_code=1,
        )

    if load_result.state == AUTHORITY_STATE_INVALID:
        return WizardLoadResult(
            project_root=resolved_root,
            blueprint_path=Path(load_result.path),
            blueprint_data={},
            incomplete=[],
            authority_state=load_result.state,
            message="Blueprint is invalid. Fix bpfw/blueprint.yaml before running wizard.",
            exit_code=1,
        )

    try:
        ensure_blueprint_can_be_written(project_root=resolved_root)
    except BlueprintLockedError:
        return WizardLoadResult(
            project_root=resolved_root,
            blueprint_path=Path(load_result.path),
            blueprint_data=load_result.data,
            incomplete=[],
            authority_state=load_result.state,
            message="Blueprint is locked. Run bpfw unlock before editing.",
            exit_code=1,
        )

    blueprint_data = load_result.data
    return WizardLoadResult(
        project_root=resolved_root,
        blueprint_path=Path(load_result.path),
        blueprint_data=blueprint_data,
        incomplete=get_incomplete_responsibilities(blueprint_data),
        authority_state=load_result.state,
    )


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
        f"  intent       {display_value(responsibility.get('intent'))}",
        f"  owner_layer  {display_value(responsibility.get('owner_layer'))}",
        f"  lifecycle    {display_value(responsibility.get('lifecycle'))}",
        f"  notes        {display_value(responsibility.get('notes'))}",
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


def complete_human_fields(project_root: Path) -> tuple[Path, int]:
    """Fill missing human fields deterministically."""

    ensure_blueprint_can_be_written(project_root=project_root)
    loader = BlueprintLoader(project_root=project_root)
    load_result = loader.load()
    blueprint_path = Path(load_result.path)
    payload = load_result.data
    responsibilities = payload.get("responsibilities", [])
    if not isinstance(responsibilities, list):
        return blueprint_path, 0

    updated_entries = 0
    for responsibility in responsibilities:
        if not isinstance(responsibility, dict):
            continue

        lifecycle_value = responsibility.get("lifecycle")
        if lifecycle_value is None or (isinstance(lifecycle_value, str) and not lifecycle_value.strip()):
            responsibility["lifecycle"] = "active"
            updated_entries += 1

        intent_value = responsibility.get("intent")
        if intent_value is None or (isinstance(intent_value, str) and not intent_value.strip()):
            responsibility_identifier = str(responsibility.get("id", "")).strip()
            canonical_name = str(responsibility.get("canonical_name", "")).strip().lower()
            generated_intent = (
                f"{canonical_name}:{responsibility_identifier}"
                if canonical_name
                else responsibility_identifier.replace("_", " ")
            )
            responsibility["intent"] = generated_intent.strip() or "define intent"
            updated_entries += 1

    save_blueprint(blueprint_path=blueprint_path, blueprint_data=payload)
    return blueprint_path, updated_entries
