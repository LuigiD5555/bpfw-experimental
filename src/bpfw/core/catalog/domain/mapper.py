"""Data mapper between raw YAML dictionaries and Pydantic domain models."""

from __future__ import annotations

from typing import Any

from bpfw.core.catalog.domain.models import BlueprintDocument, Policy, Responsibility


class BlueprintMapper:
    """Map raw blueprint dictionaries to domain objects and back without dropping extensions."""

    def from_raw(self, raw_blueprint_data: dict[str, Any]) -> BlueprintDocument:
        blocks_raw = raw_blueprint_data.get("blocks")
        block_models: list[Responsibility] = []
        if isinstance(blocks_raw, list):
            for item in blocks_raw:
                if isinstance(item, dict):
                    block_models.append(Responsibility.model_validate(item))

        policy_raw = raw_blueprint_data.get("policy")
        policy_model = Policy.model_validate(policy_raw if isinstance(policy_raw, dict) else {})

        # Start from the original payload so unknown v2+ extensions survive a
        # load/edit/save round-trip. Known sections are replaced with typed models.
        payload = dict(raw_blueprint_data)
        payload["policy"] = policy_model
        payload["blocks"] = block_models
        payload.setdefault("project", {})
        payload.setdefault("authority", {})
        payload.setdefault("includes", [])
        payload.setdefault("scenarios", [])
        return BlueprintDocument.model_validate(payload)

    def to_raw(self, document: BlueprintDocument) -> dict[str, Any]:
        # Pydantic's extra="allow" keeps unrecognised fields, so dumping the
        # complete document is safer than reconstructing a whitelist by hand.
        return document.model_dump(by_alias=True, exclude_none=True)


__all__ = ["BlueprintMapper"]
