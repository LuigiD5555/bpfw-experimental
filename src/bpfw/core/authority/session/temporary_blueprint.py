"""PURPOSE temporary unified blueprint YAML persistence for interactive authority sessions
DOMAIN  temporary blueprint sessions
"""

from pathlib import Path
from typing import Any


def write_unified_blueprint(temporary_path: Path, blueprint_data: dict[str, Any]) -> None:
    """PURPOSE write a unified blueprint document to the pending session file
    DOMAIN  temporary blueprint sessions
    """

    import yaml

    temporary_path.parent.mkdir(parents=True, exist_ok=True)
    rendered_blueprint = yaml.safe_dump(blueprint_data, sort_keys=False, allow_unicode=True)
    temporary_path.write_text(rendered_blueprint, encoding="utf-8")


def read_unified_blueprint(temporary_path: Path) -> dict[str, Any]:
    """PURPOSE read a unified blueprint document from the pending session file
    DOMAIN  temporary blueprint sessions
    """

    import yaml

    parsed_data = yaml.safe_load(temporary_path.read_text(encoding="utf-8"))
    if not isinstance(parsed_data, dict):
        raise ValueError(f"Temporary session blueprint is invalid: {temporary_path}")
    return parsed_data
