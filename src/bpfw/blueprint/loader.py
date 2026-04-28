"""Blueprint loader from project filesystem."""

from __future__ import annotations

from pathlib import Path

import yaml

from bpfw.blueprint.schema import BLUEPRINT_FILE_NAME


class BlueprintLoadError(RuntimeError):
    """Raised when blueprint loading/parsing fails."""



def load_blueprint_data(project_root: Path) -> tuple[Path, dict]:
    """Load and parse blueprint.yaml into a dictionary."""

    blueprint_path = project_root / BLUEPRINT_FILE_NAME
    if not blueprint_path.exists():
        raise BlueprintLoadError(f"{BLUEPRINT_FILE_NAME} does not exist")

    try:
        raw_content = yaml.safe_load(blueprint_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise BlueprintLoadError(f"Invalid YAML in {BLUEPRINT_FILE_NAME}: {error}") from error

    if raw_content is None:
        return blueprint_path, {}
    if not isinstance(raw_content, dict):
        raise BlueprintLoadError(f"{BLUEPRINT_FILE_NAME} root must be a mapping")

    return blueprint_path, raw_content
