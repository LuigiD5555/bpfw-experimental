"""Blueprint loader from project filesystem."""

from pathlib import Path

import yaml

from bpfw.blueprint.schema import CANONICAL_BLUEPRINT_FILE, LEGACY_BLUEPRINT_FILE


class BlueprintLoadError(RuntimeError):
    """Raised when blueprint loading/parsing fails."""


def resolve_blueprint_path(project_root: Path) -> tuple[Path, list[str]]:
    """Resolve canonical blueprint path with temporary legacy fallback."""

    warnings: list[str] = []
    canonical_blueprint_path = project_root / CANONICAL_BLUEPRINT_FILE
    legacy_blueprint_path = project_root / LEGACY_BLUEPRINT_FILE

    if canonical_blueprint_path.exists():
        return canonical_blueprint_path, warnings

    if legacy_blueprint_path.exists():
        warnings.append(
            "Deprecated blueprint path detected (blueprint.yaml). "
            "Move it to bpfw/blueprint.yaml."
        )
        return legacy_blueprint_path, warnings

    raise BlueprintLoadError(f"{CANONICAL_BLUEPRINT_FILE} does not exist")


def load_blueprint_data(project_root: Path) -> tuple[Path, dict, list[str]]:
    """Load and parse blueprint data into a dictionary."""

    blueprint_path, warnings = resolve_blueprint_path(project_root=project_root)

    try:
        raw_content = yaml.safe_load(blueprint_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise BlueprintLoadError(f"Invalid YAML in {blueprint_path}: {error}") from error

    if raw_content is None:
        return blueprint_path, {}, warnings
    if not isinstance(raw_content, dict):
        raise BlueprintLoadError(f"{blueprint_path} root must be a mapping")

    return blueprint_path, raw_content, warnings
