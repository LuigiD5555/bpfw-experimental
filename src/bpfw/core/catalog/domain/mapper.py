"""PURPOSE data mapper between raw YAML dictionaryionaries and Pydantic domain models
DOMAIN  blueprint data
"""

from __future__ import annotations

from typing import Any

from bpfw.core.catalog.domain.models import BlueprintDocument, Policy, Responsibility


class BlueprintMapper:
    """PURPOSE map raw blueprint dictionaryionaries to domain objects and back
        DOMAIN  blueprint data

    """

    def from_raw(self, raw_blueprint_data: dict[str, Any]) -> BlueprintDocument:
        blocks_raw = raw_blueprint_data.get("blocks")
        block_models: list[Responsibility] = []
        if isinstance(blocks_raw, list):
            for item in blocks_raw:
                if isinstance(item, dict):
                    block_models.append(Responsibility.model_validate(item))

        policy_raw = raw_blueprint_data.get("policy")
        policy_model = Policy.model_validate(policy_raw if isinstance(policy_raw, dict) else {})

        payload = {
            "version": raw_blueprint_data.get("version"),
            "project": raw_blueprint_data.get("project") if isinstance(raw_blueprint_data.get("project"), dict) else {},
            "policy": policy_model,
            "authority": raw_blueprint_data.get("authority") if isinstance(raw_blueprint_data.get("authority"), dict) else {},
            "includes": raw_blueprint_data.get("includes") if isinstance(raw_blueprint_data.get("includes"), list) else [],
            "blocks": block_models,
        }
        return BlueprintDocument.model_validate(payload)

    def to_raw(self, document: BlueprintDocument) -> dict[str, Any]:
        raw_blocks = [
            block.model_dump(by_alias=True, exclude_none=True)
            for block in document.blocks
        ]
        return {
            "version": document.version,
            "project": document.project,
            "policy": document.policy.model_dump(exclude_none=True),
            "authority": document.authority,
            "includes": document.includes,
            "blocks": raw_blocks,
        }


__all__ = ["BlueprintMapper"]
