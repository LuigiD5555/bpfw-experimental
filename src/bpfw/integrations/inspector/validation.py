"""Validation helpers for the inspector integration."""

from typing import Any, Dict, List

REQUIRED_SAVE_FIELDS = ("domain", "status")


def validate_required_fields(
    block: Dict[str, Any],
) -> List[str]:
    """Return list of missing required field names."""

    values = {
        "domain": block.get("domain"),
        "status": block.get("status"),
    }

    missing: List[str] = []
    for field_name in REQUIRED_SAVE_FIELDS:
        value = values.get(field_name)
        if value is None:
            missing.append(field_name)
            continue
        if isinstance(value, str) and value.strip() in {"", "-"}:
            missing.append(field_name)
    return missing
