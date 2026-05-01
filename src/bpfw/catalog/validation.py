"""Structural and lifecycle validation for BPFW blueprint authority."""

from typing import Any, Dict, List

from bpfw.catalog.lifecycle import ALLOWED_LIFECYCLES, is_allowed_lifecycle
from bpfw.catalog.models import (
    AUTHORITY_STATE_EMPTY,
    AUTHORITY_STATE_INVALID,
    AUTHORITY_STATE_MISSING,
)
from bpfw.reports.finding import FINDING_SEVERITY_BLOCK, Finding

_SOURCE = "bpfw"

_RESPONSIBILITY_REQUIRED_FIELDS = ("id", "intent", "canonical_name", "owner_layer", "lifecycle")
_LOCATION_REQUIRED_FIELDS = ("path", "symbol", "symbol_type")


def _is_blank(value: Any) -> bool:
    """Check if a value is None or an empty string."""
    return value is None or value == ""


def _safe_location_field(responsibility: Dict[str, Any], field_name: str) -> Any:
    """Safely retrieve a field from the location sub-dict."""
    location = responsibility.get("location")
    if isinstance(location, dict):
        return location.get(field_name)
    return None


def _validate_responsibility_fields(
    responsibility: Any,
    responsibility_index: int,
    findings: List[Finding],
) -> None:
    """Validate that all required catalog fields are present and non-blank."""
    if not isinstance(responsibility, dict):
        findings.append(
            Finding(
                source=_SOURCE,
                code="INCOMPLETE_RESPONSIBILITY",
                severity=FINDING_SEVERITY_BLOCK,
                message="A declared responsibility is missing required authority fields.",
                evidence={
                    "responsibility_index": responsibility_index,
                    "missing_fields": list(
                        _RESPONSIBILITY_REQUIRED_FIELDS + _LOCATION_REQUIRED_FIELDS
                    ),
                },
            )
        )
        return

    missing_fields: List[str] = []

    for field_name in _RESPONSIBILITY_REQUIRED_FIELDS:
        if _is_blank(responsibility.get(field_name)):
            missing_fields.append(field_name)

    for field_name in _LOCATION_REQUIRED_FIELDS:
        if _is_blank(_safe_location_field(responsibility, field_name)):
            missing_fields.append(f"location.{field_name}")

    if missing_fields:
        findings.append(
            Finding(
                source=_SOURCE,
                code="INCOMPLETE_RESPONSIBILITY",
                severity=FINDING_SEVERITY_BLOCK,
                path=_safe_location_field(responsibility, "path"),
                symbol=_safe_location_field(responsibility, "symbol"),
                message="A declared responsibility is missing required authority fields.",
                evidence={
                    "responsibility_index": responsibility_index,
                    "missing_fields": missing_fields,
                },
            )
        )


def _validate_responsibility_lifecycle(
    responsibility: Any,
    findings: List[Finding],
) -> None:
    """Validate that the responsibility lifecycle is allowed in the MVP."""
    if not isinstance(responsibility, dict):
        return

    lifecycle = responsibility.get("lifecycle")
    if lifecycle is not None and not is_allowed_lifecycle(lifecycle):
        findings.append(
            Finding(
                source=_SOURCE,
                code="INVALID_LIFECYCLE",
                severity=FINDING_SEVERITY_BLOCK,
                path=_safe_location_field(responsibility, "path"),
                symbol=_safe_location_field(responsibility, "symbol"),
                message="The responsibility lifecycle is not allowed in the MVP.",
                evidence={
                    "lifecycle": lifecycle,
                    "allowed_lifecycles": list(ALLOWED_LIFECYCLES),
                },
            )
        )


def _validate_duplicate_ids(
    responsibilities: List[Any],
    findings: List[Finding],
) -> None:
    """Detect responsibility entries that share the same id."""
    id_indexes: Dict[str, List[int]] = {}
    for index, responsibility in enumerate(responsibilities):
        if not isinstance(responsibility, dict):
            continue
        responsibility_id = responsibility.get("id")
        if not isinstance(responsibility_id, str) or responsibility_id == "":
            continue
        if responsibility_id not in id_indexes:
            id_indexes[responsibility_id] = []
        id_indexes[responsibility_id].append(index)

    for responsibility_id, indexes in id_indexes.items():
        if len(indexes) > 1:
            findings.append(
                Finding(
                    source=_SOURCE,
                    code="DUPLICATE_RESPONSIBILITY_ID",
                    severity=FINDING_SEVERITY_BLOCK,
                    message="More than one responsibility uses the same id.",
                    evidence={
                        "id": responsibility_id,
                        "indexes": indexes,
                    },
                )
            )


def _validate_duplicate_active_intent(
    responsibilities: List[Any],
    findings: List[Finding],
) -> None:
    """Detect intents that have more than one active responsibility."""
    intent_active_ids: Dict[str, List[str]] = {}
    for responsibility in responsibilities:
        if not isinstance(responsibility, dict):
            continue
        lifecycle = responsibility.get("lifecycle")
        if lifecycle != "active":
            continue
        intent = responsibility.get("intent")
        responsibility_id = responsibility.get("id")
        if not isinstance(intent, str) or intent == "":
            continue
        if not isinstance(responsibility_id, str) or responsibility_id == "":
            continue
        if intent not in intent_active_ids:
            intent_active_ids[intent] = []
        intent_active_ids[intent].append(responsibility_id)

    for intent, active_ids in intent_active_ids.items():
        if len(active_ids) > 1:
            findings.append(
                Finding(
                    source=_SOURCE,
                    code="DUPLICATE_ACTIVE_INTENT",
                    severity=FINDING_SEVERITY_BLOCK,
                    message="Only one responsibility can be active for the same intent.",
                    evidence={
                        "intent": intent,
                        "active_responsibility_ids": active_ids,
                    },
                )
            )


def validate_blueprint_structure(
    blueprint_data: Dict[str, Any],
    authority_state: str,
) -> List[Finding]:
    """Validate the structural integrity and lifecycle rules of a blueprint.

    Parameters
    ----------
    blueprint_data:
        Parsed YAML content of the blueprint file.
    authority_state:
        One of the ``AUTHORITY_STATE_*`` constants from
        :mod:`bpfw.catalog.models`.

    Returns
    -------
    list[Finding]
        Normalized findings.  Returns an empty list for non-actionable
        catalog states (``missing``, ``empty``).
    """

    # Non-actionable states – nothing to validate.
    if authority_state in (AUTHORITY_STATE_MISSING, AUTHORITY_STATE_EMPTY):
        return []

    # Invalid catalog file: the file could not be parsed as valid YAML.
    if authority_state == AUTHORITY_STATE_INVALID:
        return [
            Finding(
                source=_SOURCE,
                code="INVALID_BLUEPRINT",
                severity=FINDING_SEVERITY_BLOCK,
                message="The blueprint file is invalid and cannot be used as authority.",
            )
        ]

    # The responsibilities key must be a list.
    responsibilities = blueprint_data.get("responsibilities")
    if not isinstance(responsibilities, list):
        return [
            Finding(
                source=_SOURCE,
                code="INVALID_BLUEPRINT",
                severity=FINDING_SEVERITY_BLOCK,
                message="The blueprint file is invalid and cannot be used as authority.",
            )
        ]

    findings: List[Finding] = []

    # Per-responsibility structural and lifecycle checks.
    for responsibility_index, responsibility in enumerate(responsibilities):
        _validate_responsibility_fields(
            responsibility, responsibility_index, findings
        )
        _validate_responsibility_lifecycle(responsibility, findings)

    # Cross-responsibility duplicate checks.
    _validate_duplicate_ids(responsibilities, findings)
    _validate_duplicate_active_intent(responsibilities, findings)

    return findings
