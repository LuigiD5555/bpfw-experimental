"""Validation helpers for the inspector integration."""

from typing import Any, Dict, List

from bpfw.catalog.schema import get_purpose, get_status

REQUIRED_SAVE_FIELDS = ("purpose", "name", "domain", "status")


def validate_required_fields(
    block: Dict[str, Any],
) -> List[str]:
    """Return list of missing required field names."""

    values = {
        "purpose": get_purpose(block),
        "name": block.get("name"),
        "domain": block.get("domain"),
        "status": get_status(block),
    }

    missing: List[str] = []
    for field_name in REQUIRED_SAVE_FIELDS:
        value = values.get(field_name)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field_name)
    return missing
