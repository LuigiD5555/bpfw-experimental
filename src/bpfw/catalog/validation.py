"""Structural and status validation for BPFW blueprint authority."""

from typing import Any, Dict, List

from bpfw.catalog.status import ALLOWED_STATUSES, is_allowed_status
from bpfw.catalog.models import (
    AUTHORITY_STATE_EMPTY,
    AUTHORITY_STATE_INVALID,
    AUTHORITY_STATE_MISSING,
)
from bpfw.catalog.schema import get_blocks, get_code, get_kind, get_purpose, get_status
from bpfw.reports.finding import FINDING_SEVERITY_BLOCK, Finding

_SOURCE = "bpfw"

_BLOCK_REQUIRED_FIELDS = ("id", "purpose", "name", "domain", "status")
_CODE_REQUIRED_FIELDS = ("path", "symbol", "kind")


def _is_blank(value: Any) -> bool:
    """Check if a value is None or an empty string."""
    return value is None or value == ""


def _safe_code_field(block: Dict[str, Any], field_name: str) -> Any:
    """Safely retrieve a field from canonical code metadata."""
    code = get_code(block)
    if field_name == "kind":
        return get_kind(code)
    return code.get(field_name)


# ---------------------------------------------------------------------------
# Validation strategy protocol and concrete rules
# ---------------------------------------------------------------------------

class ValidationRule:
    """Base class for composable validation rules."""

    def validate(self, blocks: List[Any], findings: List[Finding]) -> None:
        """Run this rule against *blocks*, appending any findings."""


class PerBlockValidationRule(ValidationRule):
    """Rule applied to each block individually."""

    def validate_block(self, block: Any, block_index: int, findings: List[Finding]) -> None:
        """Validate a single block."""

    def validate(self, blocks: List[Any], findings: List[Finding]) -> None:
        for block_index, block in enumerate(blocks):
            self.validate_block(block, block_index, findings)


class CrossBlockValidationRule(ValidationRule):
    """Rule applied across all blocks at once."""
    pass


class BlockFieldsRule(PerBlockValidationRule):
    """Validate that all required block fields are present and non-blank."""

    def validate_block(self, block: Any, block_index: int, findings: List[Finding]) -> None:
        if not isinstance(block, dict):
            findings.append(
                Finding(
                    source=_SOURCE,
                    code="INCOMPLETE_BLOCK",
                    severity=FINDING_SEVERITY_BLOCK,
                    message=(
                        "Blueprint authority drift: a declared block in "
                        "bpfw/blueprint.yaml is incomplete and cannot be enforced."
                    ),
                    evidence={
                        "block_index": block_index,
                        "missing_fields": list(_BLOCK_REQUIRED_FIELDS + _CODE_REQUIRED_FIELDS),
                    },
                )
            )
            return

        missing_fields: List[str] = []

        for field_name in ("id", "name", "domain"):
            if _is_blank(block.get(field_name)):
                missing_fields.append(field_name)

        if _is_blank(get_purpose(block)):
            missing_fields.append("purpose")
        if _is_blank(get_status(block)):
            missing_fields.append("status")

        for field_name in _CODE_REQUIRED_FIELDS:
            if _is_blank(_safe_code_field(block, field_name)):
                missing_fields.append(f"code.{field_name}")

        if missing_fields:
            findings.append(
                Finding(
                    source=_SOURCE,
                    code="INCOMPLETE_BLOCK",
                    severity=FINDING_SEVERITY_BLOCK,
                    path=_safe_code_field(block, "path"),
                    symbol=_safe_code_field(block, "symbol"),
                    message=(
                        "Blueprint authority drift: declared block metadata is incomplete "
                        "in bpfw/blueprint.yaml."
                    ),
                    evidence={
                        "block_index": block_index,
                        "missing_fields": missing_fields,
                    },
                )
            )


class BlockStatusRule(PerBlockValidationRule):
    """Validate that the block status is allowed in the MVP."""

    def validate_block(self, block: Any, block_index: int, findings: List[Finding]) -> None:
        if not isinstance(block, dict):
            return

        status = get_status(block)
        if status is not None and not is_allowed_status(status):
            findings.append(
                Finding(
                    source=_SOURCE,
                    code="INVALID_STATUS",
                    severity=FINDING_SEVERITY_BLOCK,
                    path=_safe_code_field(block, "path"),
                    symbol=_safe_code_field(block, "symbol"),
                    message="The block status is not allowed in the MVP.",
                    evidence={
                        "status": status,
                        "allowed_statuses": list(ALLOWED_STATUSES),
                    },
                )
            )


class DuplicateIdsRule(CrossBlockValidationRule):
    """Detect block entries that share the same id."""

    def validate(self, blocks: List[Any], findings: List[Finding]) -> None:
        id_indexes: Dict[str, List[int]] = {}
        for index, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            block_id = block.get("id")
            if not isinstance(block_id, str) or block_id == "":
                continue
            if block_id not in id_indexes:
                id_indexes[block_id] = []
            id_indexes[block_id].append(index)

        for block_id, indexes in id_indexes.items():
            if len(indexes) > 1:
                findings.append(
                    Finding(
                        source=_SOURCE,
                        code="DUPLICATE_BLOCK_ID",
                        severity=FINDING_SEVERITY_BLOCK,
                        message="More than one block uses the same id.",
                        evidence={
                            "id": block_id,
                            "indexes": indexes,
                        },
                    )
                )


class DuplicateActivePurposeRule(CrossBlockValidationRule):
    """Detect purposes that have more than one active block."""

    def validate(self, blocks: List[Any], findings: List[Finding]) -> None:
        purpose_active_ids: Dict[str, List[str]] = {}
        for block in blocks:
            if not isinstance(block, dict):
                continue
            status = get_status(block)
            if status != "active":
                continue
            purpose = get_purpose(block)
            block_id = block.get("id")
            if not isinstance(purpose, str) or purpose == "":
                continue
            if not isinstance(block_id, str) or block_id == "":
                continue
            if purpose not in purpose_active_ids:
                purpose_active_ids[purpose] = []
            purpose_active_ids[purpose].append(block_id)

        for purpose, active_ids in purpose_active_ids.items():
            if len(active_ids) > 1:
                findings.append(
                    Finding(
                        source=_SOURCE,
                        code="DUPLICATE_ACTIVE_PURPOSE",
                        severity=FINDING_SEVERITY_BLOCK,
                        message="Only one block can be active for the same purpose.",
                        evidence={
                            "purpose": purpose,
                            "active_block_ids": active_ids,
                        },
                    )
                )


class BlueprintValidator:
    """Composable validation pipeline that runs ordered rules."""

    def __init__(self, rules: List[ValidationRule] | None = None) -> None:
        self.rules: List[ValidationRule] = rules or [
            BlockFieldsRule(),
            BlockStatusRule(),
            DuplicateIdsRule(),
            DuplicateActivePurposeRule(),
        ]

    def validate(self, blocks: List[Any]) -> List[Finding]:
        """Run all rules and return accumulated findings."""
        findings: List[Finding] = []
        for rule in self.rules:
            rule.validate(blocks, findings)
        return findings


# Default validator instance for public API
_default_validator = BlueprintValidator()


def validate_blueprint_structure(
    blueprint_data: Dict[str, Any],
    authority_state: str,
) -> List[Finding]:
    """Validate the structural integrity and status rules of a blueprint."""
    if authority_state in (AUTHORITY_STATE_MISSING, AUTHORITY_STATE_EMPTY):
        return []

    if authority_state == AUTHORITY_STATE_INVALID:
        return [
            Finding(
                source=_SOURCE,
                code="INVALID_BLUEPRINT",
                severity=FINDING_SEVERITY_BLOCK,
                message="The blueprint file is invalid and cannot be used as authority.",
            )
        ]

    blocks = get_blocks(blueprint_data)
    if not isinstance(blocks, list):
        return [
            Finding(
                source=_SOURCE,
                code="INVALID_BLUEPRINT",
                severity=FINDING_SEVERITY_BLOCK,
                message="The blueprint file is invalid and cannot be used as authority.",
            )
        ]

    return _default_validator.validate(blocks)
