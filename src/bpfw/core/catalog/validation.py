"""PURPOSE structural and status check for BPFW blueprint authority
DOMAIN  blueprint checks
"""

from typing import Any, Dict, List

from bpfw.core.catalog.status import ALLOWED_STATUSES, is_allowed_status
from bpfw.core.catalog.models import (
    AUTHORITY_STATE_EMPTY,
    AUTHORITY_STATE_INVALID,
    AUTHORITY_STATE_MISSING,
)
from bpfw.reports.finding import FINDING_SEVERITY_BLOCK, Finding

_SOURCE = "bpfw"

_BLOCK_REQUIRED_FIELDS = ("id", "purpose", "name", "domain", "status")
_CODE_REQUIRED_FIELDS = ("path", "symbol", "kind")


def _is_blank(value: Any) -> bool:
    """PURPOSE check if a value is None or an empty string
    DOMAIN  blueprint checks
    """
    return value is None or value == ""


def _safe_code_field(block: Dict[str, Any], field_name: str) -> Any:
    """PURPOSE safely retrieve a field from canonical code metadata
    DOMAIN  blueprint checks
    """
    code = block.get("code", {})
    if not isinstance(code, dict):
        code = {}
    if field_name == "kind":
        return code.get("kind")
    return code.get(field_name)


# ---------------------------------------------------------------------------
# Validation strategy protocol and concrete rules
# ---------------------------------------------------------------------------

class ValidationRule:
    """PURPOSE base class for composable check rules
    DOMAIN  blueprint checks
    """

    def validate(self, blocks: List[Any], findings: List[Finding]) -> None:
        """PURPOSE run this rule against *blocks*, appending any findings
        DOMAIN  blueprint checks
        """


class PerBlockValidationRule(ValidationRule):
    """PURPOSE rule applied to each block individually
    DOMAIN  blueprint checks
    """

    def validate_block(self, block: Any, block_index: int, findings: List[Finding]) -> None:
        """PURPOSE check a single block
        DOMAIN  blueprint checks
        """

    def validate(self, blocks: List[Any], findings: List[Finding]) -> None:
        for block_index, block in enumerate(blocks):
            self.validate_block(block, block_index, findings)


class CrossBlockValidationRule(ValidationRule):
    """PURPOSE rule applied across all blocks at once
    DOMAIN  blueprint checks
    """
    pass


class BlockFieldsRule(PerBlockValidationRule):
    """PURPOSE check that all required block fields are present and non-blank
    DOMAIN  blueprint checks
    """

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

        if _is_blank(block.get("purpose")):
            missing_fields.append("purpose")
        if _is_blank(block.get("status")):
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
    """PURPOSE check that the block status is allowed in the
    DOMAIN  blueprint checks
    """

    def validate_block(self, block: Any, block_index: int, findings: List[Finding]) -> None:
        if not isinstance(block, dict):
            return

        status = block.get("status")
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
    """PURPOSE find block entries that share the same id
    DOMAIN  blueprint checks
    """

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
    """PURPOSE find purposes that have more than one active block
    DOMAIN  blueprint checks
    """

    def validate(self, blocks: List[Any], findings: List[Finding]) -> None:
        purpose_active_ids: Dict[str, List[str]] = {}
        for block in blocks:
            if not isinstance(block, dict):
                continue
            status = block.get("status")
            if status != "active":
                continue
            purpose = block.get("purpose")
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
    """PURPOSE composable check pipeline that runs ordered rules
    DOMAIN  blueprint checks
    """

    def __init__(self, rules: List[ValidationRule] | None = None) -> None:
        self.rules: List[ValidationRule] = rules or [
            BlockFieldsRule(),
            BlockStatusRule(),
            DuplicateIdsRule(),
            DuplicateActivePurposeRule(),
        ]

    def validate(self, blocks: List[Any]) -> List[Finding]:
        """PURPOSE run all rules and return accumulated findings
        DOMAIN  blueprint checks
        """
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
    """PURPOSE check the structural integrity and status rules of a blueprint
    DOMAIN  blueprint checks
    """
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

    blocks = blueprint_data.get("blocks", [])
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
