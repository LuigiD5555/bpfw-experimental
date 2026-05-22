"""Blueprint assembler for converting PlannerState to YAML."""

from pathlib import Path
from typing import Any, Dict, List

from bpfw.catalog.writer import write_blueprint
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
        blueprint_data = {
            "version": 1,
            "project": BlueprintAssembler._assemble_project(state),
            "policy": BlueprintAssembler._assemble_policy(state),
            "blocks": BlueprintAssembler._assemble_blocks(state),
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
            "one_active_block_per_purpose": config.single_active_per_purpose,
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
    def _assemble_blocks(state: PlannerState) -> List[Dict[str, Any]]:
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
            )
            blocks.append(block)
        
        return blocks
    
    @staticmethod
    def _assemble_block(
        box: PlannerBox,
        connections: List[PlannerConnection],
    ) -> Dict[str, Any]:
        """Assemble a single block.
        
        Args:
            box: The box to convert.
            connections: Connections from this box.
        
        Returns:
            Block dictionary.
        """
        # Build connections from accepted planner connections
        block_connections = []
        for conn in connections:
            block_connections.append({
                "target": conn.target_box_id,
                "meaning": conn.relationship,
            })
        
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
        
        # Build block
        block = {
            "id": box.id,
            "purpose": box.purpose,
            "name": box.name,
            "domain": box.domain,
            "status": box.lifecycle,
            "code": code,
            "detected": detected,
            "entrypoints": [],
            "connections": block_connections,
            "uniqueness": uniqueness,
            "replacement": replacement,
            "notes": box.notes,
        }
        
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
            # Fallback: if authority doesn't exist, this is likely init
            # Use regular write_blueprint for init case
            write_blueprint(blueprint_path=blueprint_path, blueprint_data=blueprint_data)
