"""Interactive wizard for BPFW MVP catalog completion."""

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
from bpfw.core.errors import BlueprintLockedError


ALLOWED_LIFECYCLES = ("active", "experimental", "legacy", "deprecated")

LIFECYCLE_MENU = {
    "1": "active",
    "2": "experimental",
    "3": "legacy",
    "4": "deprecated",
}

REQUIRED_HUMAN_FIELDS = ("intent", "canonical_name", "owner_layer", "lifecycle")


def get_incomplete_responsibilities(
    blueprint_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Return responsibilities that have at least one missing required human field.

    Required human fields are: intent, canonical_name, owner_layer, lifecycle.

    Args:
        blueprint_data: Parsed blueprint dictionary.

    Returns:
        List of responsibility dicts with incomplete human fields.
    """
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


def prompt_for_lifecycle() -> str:
    """Display lifecycle menu and return the selected lifecycle string.

    Accepts either the numeric option (1-4) or the exact lifecycle name.

    Returns:
        One of: active, experimental, legacy, deprecated.
    """
    print("Lifecycle:")
    print("  1) active")
    print("  2) experimental")
    print("  3) legacy")
    print("  4) deprecated")

    while True:
        user_input = input("> ").strip()
        if user_input in LIFECYCLE_MENU:
            return LIFECYCLE_MENU[user_input]
        if user_input in ALLOWED_LIFECYCLES:
            return user_input
        print("Invalid lifecycle. Enter 1-4 or exact lifecycle name.")


def save_blueprint(
    blueprint_path: Path,
    blueprint_data: Dict[str, Any],
) -> None:
    """Save blueprint data to the YAML file.

    Args:
        blueprint_path: Path to bpfw/blueprint.yaml.
        blueprint_data: Blueprint data dictionary to serialize.
    """
    rendered = yaml.dump(blueprint_data, sort_keys=False, allow_unicode=True)
    blueprint_path.write_text(rendered, encoding="utf-8")


def run_wizard(project_root: Path) -> int:
    """Run the interactive wizard to complete required human fields.

    Steps:
        1. Resolve project root.
        2. Load blueprint.
        3. Exit 1 if blueprint is missing.
        4. Exit 1 if blueprint is invalid.
        5. Exit 1 if blueprint is locked.
        6. Find responsibilities with missing human fields.
        7. Prompt for each incomplete responsibility.
        8. Save after each responsibility.
        9. Print completion message.

    Args:
        project_root: Root directory of the project.

    Returns:
        Exit code: 0 on success, 1 on error or refusal.
    """
    project_root = project_root.resolve()

    # Step 2: Load blueprint
    loader = BlueprintLoader(project_root=project_root)
    load_result = loader.load()

    # Step 3: If blueprint missing
    if load_result.state == AUTHORITY_STATE_MISSING:
        print("No blueprint found. Run bpfw init first.")
        return 1

    # Step 4: If blueprint invalid
    if load_result.state == AUTHORITY_STATE_INVALID:
        print("Blueprint is invalid. Fix bpfw/blueprint.yaml before running wizard.")
        return 1

    # Step 5: If blueprint is locked
    try:
        ensure_blueprint_can_be_written(project_root=project_root)
    except BlueprintLockedError:
        print("Blueprint is locked. Run bpfw unlock before editing.")
        return 1

    blueprint_data = load_result.data
    blueprint_path = Path(load_result.path)

    # Step 6: Find incomplete responsibilities
    incomplete = get_incomplete_responsibilities(blueprint_data)

    if not incomplete:
        if load_result.state == AUTHORITY_STATE_EMPTY:
            print("No responsibilities to complete.")
        else:
            print("All responsibilities are already complete.")
        return 0

    total = len(incomplete)

    # Step 7-8: Prompt for each incomplete responsibility
    for index, responsibility in enumerate(incomplete, start=1):
        location = responsibility.get("location", {})
        detected = responsibility.get("detected", {})

        resp_path = location.get("path", "unknown")
        symbol = location.get("symbol", "unknown")
        symbol_type = location.get("symbol_type", "unknown")
        methods = detected.get("methods", [])
        docstring = detected.get("docstring")

        print()
        print(f"[{index}/{total}] {resp_path}::{symbol}")
        print(f"Type: {symbol_type}")

        if methods:
            print("Detected methods:")
            for method_name in methods:
                print(f"  - {method_name}")

        print("Docstring:")
        if docstring:
            print(f"  {docstring}")
        else:
            print("  n/a")

        # Intent (required, cannot be empty)
        while True:
            intent_input = input("Intent: ").strip()
            if intent_input:
                responsibility["intent"] = intent_input
                break
            print("Intent cannot be empty.")

        # Canonical name (empty keeps current value)
        current_canonical = responsibility.get("canonical_name", "")
        canonical_input = input("Canonical name: ").strip()
        if canonical_input:
            responsibility["canonical_name"] = canonical_input
        # If empty, keep current canonical_name if present

        # Owner layer (required, cannot be empty)
        while True:
            owner_input = input("Owner layer: ").strip()
            if owner_input:
                responsibility["owner_layer"] = owner_input
                break
            print("Owner layer cannot be empty.")

        # Lifecycle (validated selection)
        lifecycle_value = prompt_for_lifecycle()
        responsibility["lifecycle"] = lifecycle_value

        # Save after each responsibility
        save_blueprint(blueprint_path, blueprint_data)
        print("Saved.")

    # Step 9: Completion message
    print()
    print("Wizard completed.")
    print()
    print("Next:")
    print("  bpfw verify")
    print("  bpfw lock")

    return 0


def complete_human_fields(project_root: Path) -> tuple[Path, int]:
    """Fill missing intent and lifecycle fields deterministically.

    This is the non-interactive fallback used by the engine pipeline.
    It assigns default values without prompting the user.

    Args:
        project_root: Root directory of the project.

    Returns:
        Tuple of (blueprint_path, updated_entry_count).
    """
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
            canonical_name = (
                str(responsibility.get("canonical_name", "")).strip().lower()
            )
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