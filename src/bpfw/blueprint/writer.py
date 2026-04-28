from __future__ import annotations

from pathlib import Path

import yaml

from bpfw.blueprint.models import BlueprintModel


class BlueprintWriter:
    """Writes blueprint files using deterministic formatting and atomic replacement."""

    def write(self, project_root: Path, blueprint: BlueprintModel) -> Path:
        blueprint_path = project_root / "blueprint.yaml"
        temporary_path = project_root / "blueprint.yaml.tmp"

        responsibilities_payload = []
        for responsibility in sorted(blueprint.responsibilities, key=lambda item: item.responsibility_id):
            responsibilities_payload.append(
                {
                    "responsibility_id": responsibility.responsibility_id,
                    "canonical_name": responsibility.canonical_name,
                    "owner_layer": responsibility.owner_layer,
                    "lifecycle_state": responsibility.lifecycle_state,
                    "allowed_files": responsibility.allowed_files,
                    "allowed_symbols": responsibility.allowed_symbols,
                    "allowed_implementations": [
                        {
                            "implementation_id": implementation.implementation_id,
                            "class_name": implementation.class_name,
                            "file": implementation.file,
                            "lifecycle_state": implementation.lifecycle_state,
                            "replacement_id": implementation.replacement_id,
                            "disabled_reason": implementation.disabled_reason,
                            "removal_plan": implementation.removal_plan,
                        }
                        for implementation in responsibility.allowed_implementations
                    ],
                    "active_implementation": responsibility.active_implementation,
                    "forbidden_duplicates": responsibility.forbidden_duplicates,
                    "mutability": responsibility.mutability,
                    "owner": responsibility.owner,
                }
            )

        payload = {
            "version": blueprint.version,
            "responsibilities": responsibilities_payload,
            "locked_resources": [
                {
                    "resource_id": item.resource_id,
                    "path": item.path,
                    "mutability": item.mutability,
                    "owner": item.owner,
                }
                for item in blueprint.locked_resources
            ],
        }

        rendered = yaml.safe_dump(payload, sort_keys=False)
        yaml.safe_load(rendered)
        temporary_path.write_text(rendered, encoding="utf-8")
        temporary_path.replace(blueprint_path)
        return blueprint_path
