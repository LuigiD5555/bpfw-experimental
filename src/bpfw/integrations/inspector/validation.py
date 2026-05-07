"""Validation helpers for the inspector integration."""

from typing import Any, Dict, List

REQUIRED_SAVE_FIELDS = ("intent", "name", "domain", "lifecycle")


def validate_required_fields(
    responsibility: Dict[str, Any],
) -> List[str]:
    """Return list of missing required field names."""

    missing: List[str] = []
    for field_name in REQUIRED_SAVE_FIELDS:
        value = responsibility.get(field_name)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field_name)
    return missing