"""Blueprint assembler for converting PlannerState to YAML."""

from pathlib import Path
from typing import Any, Dict, List

from bpfw.catalog.access_control import ensure_blueprint_can_be_written
from bpfw.catalog.paths import resolve_blueprint_path
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
            "responsibilities": BlueprintAssembler._assemble_responsibilities(state),
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
            "allowed_lifecycles": config.allowed_lifecycles,
            "single_active_per_intent": config.single_active_per_intent,
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
    def _assemble_responsibilities(state: PlannerState) -> List[Dict[str, Any]]:
        """Assemble responsibilities section.
        
        Args:
            state: Current planner state.
        
        Returns:
            List of responsibility dictionaries.
        """
        responsibilities = []
        
        # Build a mapping of connections by source box
        connections_by_source: Dict[str, List[PlannerConnection]] = {}
        for conn in state.connections:
            if conn.status != "accepted":
                continue
            if conn.source_box_id not in connections_by_source:
                connections_by_source[conn.source_box_id] = []
            connections_by_source[conn.source_box_id].append(conn)
        
        for box in state.boxes:
            responsibility = BlueprintAssembler._assemble_responsibility(
                box,
                connections_by_source.get(box.id, []),
            )
            responsibilities.append(responsibility)
        
        return responsibilities
    
    @staticmethod
    def _assemble_responsibility(
        box: PlannerBox,
        connections: List[PlannerConnection],
    ) -> Dict[str, Any]:
        """Assemble a single responsibility.
        
        Args:
            box: The box to convert.
            connections: Connections from this box.
        
        Returns:
            Responsibility dictionary.
        """
        # Build related_code from connections
        related_code = []
        for conn in connections:
            related_code.append({
                "target": conn.target_box_id,
                "relationship": conn.relationship,
            })
        
        # Build location
        location = {
            "path": box.path,
            "module": box.module,
            "symbol": box.symbol,
            "symbol_type": box.symbol_type,
            "start_line": None,
            "end_line": None,
        }
        
        # Build detected section
        detected = {
            "qualified_name": box.qualified_name,
            "kind": box.symbol_type,
        }
        
        # Build duplicate_policy
        duplicate_policy = {
            "group": box.duplicate_group,
            "allow_multiple_non_active": True,
            "forbidden_active_duplicates": True,
            "suspected_duplicates": [],
        }
        
        # Build replacement section
        replacement = {
            "replaces": None,
            "replaced_by": None,
            "reason": None,
        }
        
        # Build responsibility
        responsibility = {
            "id": box.id,
            "intent": box.intent,
            "name": box.name,
            "domain": box.domain,
            "lifecycle": box.lifecycle,
            "location": location,
            "detected": detected,
            "entrypoints": [],
            "related_code": related_code,
            "duplicate_policy": duplicate_policy,
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
                responsibility["interface"] = interface_data
        
        return responsibility


class BlueprintYamlWriter:
    """Write assembled blueprint data to YAML file."""
    
    @staticmethod
    def write(blueprint_path: Path, blueprint_data: Dict[str, Any]) -> None:
        """Write blueprint data to YAML file.
        
        Args:
            blueprint_path: Path to the blueprint file.
            blueprint_data: Blueprint data to write.
        """
        try:
            import yaml
        except ImportError:
            raise ImportError("PyYAML is required but not installed")
        
        # Ensure blueprint can be written
        project_root = blueprint_path.parent.parent
        ensure_blueprint_can_be_written(project_root=project_root)
        
        # Create directory if needed
        blueprint_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Render and write YAML
        rendered = yaml.safe_dump(blueprint_data, sort_keys=False, allow_unicode=True)
        blueprint_path.write_text(rendered, encoding="utf-8")
