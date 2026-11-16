"""Blueprint assembler for converting PlannerState to YAML."""

from pathlib import Path
from typing import Any, Dict, List

from bpfw.core.catalog.writer import write_blueprint
from bpfw.integrations.planner.models import PlannerBox, PlannerConnection, PlannerState


class BlueprintAssembler:
    """Convert PlannerState to blueprint.yaml dictionary."""

    @staticmethod
    def assemble(state: PlannerState) -> Dict[str, Any]:
        """Assemble planner state into blueprint data.

        Args:
            state: Current planner state.

        Returns:
            Dictionary ready for YAML serialization.
        """
        uses_v2 = state.blueprint_version >= 2 or any(
            box.kind != "code" or box.intent_summary or box.guarantees or box.assumptions or box.invariants or box.artifacts
            for box in state.boxes
        )
        blueprint_data = {
            "version": 2 if uses_v2 else 1,
            "project": BlueprintAssembler._assemble_project(state),
            "policy": BlueprintAssembler._assemble_policy(state),
            "blocks": BlueprintAssembler._assemble_blocks(state, uses_v2=uses_v2),
        }

        return blueprint_data

    @staticmethod
    def _assemble_project(state: PlannerState) -> Dict[str, Any]:
        """Assemble project section.

        Args:
            state: Current planner state.

        Returns:
            Project dictionary.
        """
        config = state.project_config

        return {
            "id": config.project_id,
            "name": config.project_name,
            "root": config.root,
            "language": config.language,
            "source_roots": config.source_roots,
            "ignored_paths": config.ignored_paths,
        }

    @staticmethod
    def _assemble_policy(state: PlannerState) -> Dict[str, Any]:
        """Assemble policy section.

        Args:
            state: Current planner state.

        Returns:
            Policy dictionary.
        """
        config = state.project_config

        policy = {
            "mode": config.policy_mode,
            "empty_blueprint_allows_execution": config.empty_blueprint_allows_execution,
            "defined_blueprint_blocks_on_drift": config.defined_blueprint_blocks_on_drift,
            "allowed_statuses": config.allowed_lifecycles,
            "duplicate_detection": {"block_active_duplicate_profiles": config.block_active_duplicate_profiles},
            "undeclared_code_blocks": config.undeclared_code_blocks,
            "missing_declared_code_blocks": config.missing_declared_code_blocks,
            "security": {
                "no_secrets_in_blueprint": config.security.no_secrets_in_blueprint,
                "public_safe_mode": config.security.public_safe_mode,
                "detected_detail_level": config.security.detected_detail_level,
            },
        }

        return policy

    @staticmethod
    def _assemble_blocks(state: PlannerState, *, uses_v2: bool = False) -> List[Dict[str, Any]]:
        """Assemble blocks section.

        Args:
            state: Current planner state.

        Returns:
            List of block dictionaries.
        """
        blocks = []

        # Build a mapping of connections by source box
        connections_by_source: Dict[str, List[PlannerConnection]] = {}
        for conn in state.connections:
            if conn.status != "accepted":
                continue
            if conn.source_box_id not in connections_by_source:
                connections_by_source[conn.source_box_id] = []
            connections_by_source[conn.source_box_id].append(conn)

        for box in state.boxes:
            block = BlueprintAssembler._assemble_block(
                box,
                connections_by_source.get(box.id, []),
                uses_v2=uses_v2,
            )
            blocks.append(block)

        return blocks

    @staticmethod
    def _assemble_block(
        box: PlannerBox,
        connections: List[PlannerConnection],
        *,
        uses_v2: bool = False,
    ) -> Dict[str, Any]:
        """Assemble a single block.

        Args:
            box: The box to convert.
            connections: Connections from this box.

        Returns:
            Block dictionary.
        """
        # Build connections from accepted planner connections. v2 can consume
        # the typed relationship while `meaning` remains for v1 compatibility.
        block_connections = []
        for conn in connections:
            item = {
                "target": conn.target_box_id,
                "meaning": conn.relationship,
            }
            if uses_v2:
                item["relationship"] = conn.relationship
                item["provenance"] = "declared"
            block_connections.append(item)

        # Build code metadata
        code = {
            "path": box.path,
            "module": box.module,
            "symbol": box.symbol,
            "kind": box.symbol_type,
            "start_line": None,
            "end_line": None,
        }

        # Build detected section
        detected = {
            "qualified_name": box.qualified_name,
            "kind": box.symbol_type,
        }

        # Build uniqueness metadata
        uniqueness = {
            "group": box.duplicate_group,
            "allow_multiple_non_active": True,
            "forbid_active_duplicates": True,
            "suspected_duplicates": [],
        }

        # Build replacement section
        replacement = {
            "replaces": None,
            "replaced_by": None,
            "reason": None,
        }

        # Build logical block. Only code components (or components with an
        # explicit legacy code location) receive `code`/`detected` metadata.
        block = {
            "id": box.id,
            "purpose": box.purpose,
            "domain": box.domain,
            "status": box.lifecycle,
            "entrypoints": [],
            "connections": block_connections,
            "uniqueness": uniqueness,
            "replacement": replacement,
            "notes": box.notes,
        }
        if box.kind == "code" or box.path or box.symbol:
            block["code"] = code
            block["detected"] = detected

        if box.kind != "code":
            block["kind"] = box.kind
        if box.intent_summary or box.guarantees or box.assumptions:
            block["intent"] = {
                "summary": box.intent_summary,
                "guarantees": list(box.guarantees),
                "assumptions": list(box.assumptions),
            }
        if box.invariants:
            block["invariants"] = [dict(value) for value in box.invariants]
        if box.artifacts:
            block["artifacts"] = [dict(value) for value in box.artifacts]

        # Add interface if present
        if box.interface:
            interface_data = {}

            if box.interface.inputs:
                interface_data["inputs"] = [
                    {
                        "name": inp.name,
                        "type": inp.type,
                        "default": inp.default,
                        "required": inp.required,
                        "description": inp.description,
                    }
                    for inp in box.interface.inputs
                ]

            if box.interface.output:
                interface_data["output"] = {
                    "type": box.interface.output.type,
                    "description": box.interface.output.description,
                }

            if interface_data:
                block["interface"] = interface_data

        return block


class BlueprintYamlWriter:
    """Write assembled blueprint data to YAML file."""

    @staticmethod
    def write(blueprint_path: Path, blueprint_data: Dict[str, Any]) -> None:
        """Write blueprint data to YAML file using AuthorityRepository.

        Args:
            blueprint_path: Path to the blueprint file.
            blueprint_data: Blueprint data to write.
        """
        from bpfw.core.authority import AuthorityRepository

        # Get project root from blueprint path
        project_root = blueprint_path.parent.parent

        # Use AuthorityRepository to save sharded authority
        repository = AuthorityRepository(project_root)

        # Load current document to preserve authority config
        try:
            document = repository.load()
            # Update blueprint_data while preserving authority metadata
            document.blueprint_data = blueprint_data
            repository.save(document)
        except Exception:
            from bpfw.core.authority.sqlite.migration import active_backend
            if active_backend(project_root) == 'sqlite':
                raise  # SQLite errors must not silently trigger legacy writer fallback.
            # Fallback: if authority doesn't exist, this is likely init
            # Use regular write_blueprint for init case
            write_blueprint(blueprint_path=blueprint_path, blueprint_data=blueprint_data)
