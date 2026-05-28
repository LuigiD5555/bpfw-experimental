"""PURPOSE build low-level patch plans from Blueprint Engine requests
DOMAIN  approved blueprint changes
"""

from pathlib import Path
from typing import Any

from bpfw.core.authority.errors import AuthorityError
from bpfw.core.authority.patch import (
    AddCoveredCodeOperation,
    AddIgnoreRuleOperation,
    AuthorityPatchPlan,
    CreateBlockOperation,
    CreateShardFileOperation,
    DeleteBlockOperation,
    DeleteShardFileOperation,
    MoveBlockOperation,
    MoveShardFileOperation,
    RemoveCoveredCodeOperation,
    RemoveIgnoreRuleOperation,
    RenameShardFileOperation,
    UpdateBlockCodeReferenceOperation,
    UpdateBlockLocationOperation,
    UpdateBlockMetadataOperation,
    UpdateBlockSymbolOperation,
)
from bpfw.core.blueprint_engine.models import BlueprintChangeKind, BlueprintChangeRequest


class BlueprintPlanBuilder:
    """PURPOSE convert approved change requests into file change plans
        DOMAIN  approved blueprint changes
        """

    def build_plan(self, requests: list[BlueprintChangeRequest]) -> AuthorityPatchPlan:
        """PURPOSE build a patch plan from change requests
        DOMAIN  approved blueprint changes
        """
        plan = AuthorityPatchPlan()
        for request in requests:
            plan.add_operation(self._build_operation(request))
        return plan

    def _build_operation(self, request: BlueprintChangeRequest):  # noqa: ANN202
        """PURPOSE build one patch operation from a request
        DOMAIN  approved blueprint changes
        """
        kind = request.kind
        payload = request.payload

        if kind == BlueprintChangeKind.CREATE_BLOCK:
            return CreateBlockOperation(
                block_data=self._required_dict(payload, "block_data"),
                target_shard_path=self._required_path(payload, "target_shard_path"),
                create_target_if_missing=bool(payload.get("create_target_if_missing", True)),
            )
        if kind == BlueprintChangeKind.DELETE_BLOCK:
            return DeleteBlockOperation(
                block_id=self._required_string(payload, "block_id"),
                source_shard_path=self._required_path(payload, "source_shard_path"),
            )
        if kind == BlueprintChangeKind.UPDATE_METADATA:
            return UpdateBlockMetadataOperation(
                block_id=self._required_string(payload, "block_id"),
                source_shard_path=self._required_path(payload, "source_shard_path"),
                metadata_changes=self._required_dict(payload, "metadata_changes"),
            )
        if kind == BlueprintChangeKind.UPDATE_LOCATION:
            return UpdateBlockLocationOperation(
                block_id=self._required_string(payload, "block_id"),
                source_shard_path=self._required_path(payload, "source_shard_path"),
                new_path=self._required_string(payload, "new_path"),
            )
        if kind == BlueprintChangeKind.UPDATE_SYMBOL:
            return UpdateBlockSymbolOperation(
                block_id=self._required_string(payload, "block_id"),
                source_shard_path=self._required_path(payload, "source_shard_path"),
                new_symbol=self._required_string(payload, "new_symbol"),
                new_name=self._optional_string(payload, "new_name"),
            )
        if kind == BlueprintChangeKind.UPDATE_CODE_REFERENCE:
            return UpdateBlockCodeReferenceOperation(
                block_id=self._required_string(payload, "block_id"),
                source_shard_path=self._required_path(payload, "source_shard_path"),
                new_path=self._required_string(payload, "new_path"),
                new_symbol=self._required_string(payload, "new_symbol"),
                new_kind=self._optional_string(payload, "new_kind"),
                new_name=self._optional_string(payload, "new_name"),
            )
        if kind == BlueprintChangeKind.MOVE_BLOCK:
            return MoveBlockOperation(
                block_id=self._required_string(payload, "block_id"),
                source_shard_path=self._required_path(payload, "source_shard_path"),
                target_shard_path=self._required_path(payload, "target_shard_path"),
                create_target_if_missing=bool(payload.get("create_target_if_missing", True)),
            )
        if kind == BlueprintChangeKind.CREATE_SHARD:
            return CreateShardFileOperation(
                shard_path=self._required_path(payload, "shard_path"),
                initial_blocks=self._optional_blocks(payload),
            )
        if kind == BlueprintChangeKind.DELETE_SHARD:
            return DeleteShardFileOperation(
                shard_path=self._required_path(payload, "shard_path"),
                require_empty=bool(payload.get("require_empty", True)),
            )
        if kind == BlueprintChangeKind.RENAME_SHARD:
            return RenameShardFileOperation(
                source_shard_path=self._required_path(payload, "source_shard_path"),
                target_shard_path=self._required_path(payload, "target_shard_path"),
            )
        if kind == BlueprintChangeKind.MOVE_SHARD:
            return MoveShardFileOperation(
                source_shard_path=self._required_path(payload, "source_shard_path"),
                target_shard_path=self._required_path(payload, "target_shard_path"),
            )
        if kind == BlueprintChangeKind.ADD_IGNORE_RULE:
            return AddIgnoreRuleOperation(
                rule_data=self._required_dict(payload, "rule_data"),
            )
        if kind == BlueprintChangeKind.REMOVE_IGNORE_RULE:
            return RemoveIgnoreRuleOperation(
                rule_data=self._required_dict(payload, "rule_data"),
            )
        if kind == BlueprintChangeKind.ADD_COVERED_CODE:
            return AddCoveredCodeOperation(
                rule_data=self._required_dict(payload, "rule_data"),
            )
        if kind == BlueprintChangeKind.REMOVE_COVERED_CODE:
            return RemoveCoveredCodeOperation(
                rule_data=self._required_dict(payload, "rule_data"),
            )

        raise AuthorityError(f"Unsupported BlueprintChangeKind: {kind}")

    def _required_string(self, payload: dict[str, Any], key: str) -> str:
        """PURPOSE read a required non-empty string from a data
                DOMAIN  approved blueprint changes

        """
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise AuthorityError(f"Blueprint change payload requires non-empty string '{key}'.")
        return value

    def _optional_string(self, payload: dict[str, Any], key: str) -> str | None:
        """PURPOSE read an string from a data
                DOMAIN  approved blueprint changes

        """
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise AuthorityError(f"Blueprint change payload optional '{key}' must be a non-empty string.")
        return value

    def _required_path(self, payload: dict[str, Any], key: str) -> Path:
        """PURPOSE read a required path from a data
                DOMAIN  approved blueprint changes

        """
        value = payload.get(key)
        if isinstance(value, Path):
            return value
        if isinstance(value, str) and value.strip():
            return Path(value)
        raise AuthorityError(f"Blueprint change payload requires path '{key}'.")

    def _required_dict(self, payload: dict[str, Any], key: str) -> dict[str, Any]:
        """PURPOSE read a required dictionaryionary from a data
                DOMAIN  approved blueprint changes

        """
        value = payload.get(key)
        if not isinstance(value, dict) or not value:
            raise AuthorityError(f"Blueprint change payload requires non-empty dict '{key}'.")
        return value

    def _optional_blocks(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """PURPOSE read initial shard blocks
        DOMAIN  approved blueprint changes
        """
        value = payload.get("initial_blocks", [])
        if not isinstance(value, list):
            raise AuthorityError("initial_blocks must be a list when provided.")
        for block in value:
            if not isinstance(block, dict):
                raise AuthorityError("initial_blocks must contain dictionaries only.")
        return value
