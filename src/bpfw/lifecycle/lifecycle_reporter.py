"""Reporter helpers for lifecycle validation evidence."""

from __future__ import annotations

from bpfw.blueprint.models import BlueprintValidationError



def summarize_lifecycle_errors(errors: list[BlueprintValidationError]) -> dict[str, str]:
    """Build compact machine-friendly lifecycle error summary."""

    if not errors:
        return {"lifecycle_status": "ok", "lifecycle_error_count": "0"}
    return {
        "lifecycle_status": "block",
        "lifecycle_error_count": str(len(errors)),
        "first_lifecycle_error_code": errors[0].code,
    }
