"""Wizard helpers for MVP catalog completion."""

from pathlib import Path

import yaml

from bpfw.blueprint.loader import load_blueprint_data


DEFAULT_LIFECYCLE = "active"


def complete_human_fields(project_root: Path) -> tuple[Path, int]:
    """Fill missing intent and lifecycle fields deterministically."""

    blueprint_path, payload, _warnings = load_blueprint_data(project_root=project_root)
    responsibilities = payload.get("responsibilities", [])
    if not isinstance(responsibilities, list):
        return blueprint_path, 0

    updated_entries = 0
    for responsibility in responsibilities:
        if not isinstance(responsibility, dict):
            continue

        if not str(responsibility.get("lifecycle_state", "")).strip():
            responsibility["lifecycle_state"] = DEFAULT_LIFECYCLE
            updated_entries += 1

        if not str(responsibility.get("intent", "")).strip():
            responsibility_identifier = str(responsibility.get("responsibility_id", "")).strip()
            canonical_name = str(responsibility.get("canonical_name", "")).strip().lower()
            generated_intent = (
                f"{canonical_name}:{responsibility_identifier}"
                if canonical_name
                else responsibility_identifier.replace("_", " ")
            )
            responsibility["intent"] = generated_intent.strip() or "define intent"
            updated_entries += 1

    rendered = yaml.safe_dump(payload, sort_keys=False)
    blueprint_path.write_text(rendered, encoding="utf-8")
    return blueprint_path, updated_entries
