"""Minimal wizard integration for BPFW MVP catalog completion."""

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
from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.result import OptionalIntegrationResult

REQUIRED_HUMAN_FIELDS = ("intent", "canonical_name", "owner_layer", "lifecycle")


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


def _clean_string(value: Any) -> str | None:
    """Return a stripped string or None for blank values."""

    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def suggest_owner_layer(responsibility: Dict[str, Any]) -> str | None:
    """Suggest owner_layer from the code path."""

    location = responsibility.get("location", {})
    if not isinstance(location, dict):
        return None

    path = _clean_string(location.get("path"))
    if path is None:
        return None

    for marker in ("src/bpfw/", "bpfw/"):
        if marker in path:
            remainder = path.split(marker, 1)[1]
            layer = remainder.split("/", 1)[0]
            if layer:
                return layer
    return None


def apply_automatic_authority_fields(blueprint_data: Dict[str, Any]) -> None:
    """Derive authority fields that do not require interactive review."""

    responsibilities = blueprint_data.get("responsibilities", [])
    if not isinstance(responsibilities, list):
        return

    grouped_responsibilities: dict[str, list[dict[str, Any]]] = {}
    for responsibility in responsibilities:
        if not isinstance(responsibility, dict):
            continue
        intent = _clean_string(responsibility.get("intent"))
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

    rendered = yaml.dump(payload, sort_keys=False, allow_unicode=True)
    blueprint_path.write_text(rendered, encoding="utf-8")
    return blueprint_path, updated_entries


def run_wizard(project_root: Path) -> int:
    """Run the minimal wizard integration."""

    project_root = project_root.resolve()
    loader = BlueprintLoader(project_root=project_root)
    load_result = loader.load()

    if load_result.state == AUTHORITY_STATE_MISSING:
        print("No blueprint found. Run bpfw init first.")
        return 1

    if load_result.state == AUTHORITY_STATE_INVALID:
        print("Blueprint is invalid. Fix bpfw/blueprint.yaml before running wizard.")
        return 1

    try:
        ensure_blueprint_can_be_written(project_root=project_root)
    except BlueprintLockedError:
        print("Blueprint is locked. Run bpfw unlock before editing.")
        return 1

    incomplete = get_incomplete_responsibilities(load_result.data)
    if not incomplete:
        if load_result.state == AUTHORITY_STATE_EMPTY:
            print("No responsibilities to complete.")
        else:
            print("All responsibilities are already complete.")
        return 0

    blueprint_path, updated_entries = complete_human_fields(project_root=project_root)
    print(f"Wizard completed. Updated fields: {updated_entries}")
    print(f"Blueprint saved at: {blueprint_path}")
    return 0


class RichWizardIntegration(OptionalIntegration):
    """Optional wizard integration for catalog completion."""

    name = "wizard"

    def is_available(self) -> bool:
        """Return True when the wizard integration can run."""

        return True

    def run(self, project_root: Path) -> OptionalIntegrationResult:
        """Run the wizard integration."""

        exit_code = run_wizard(project_root=project_root)
        return OptionalIntegrationResult(message="", exit_code=exit_code)
