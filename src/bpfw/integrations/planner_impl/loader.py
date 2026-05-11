"""Blueprint state loader for the Planner integration."""

from pathlib import Path
from typing import Any, Dict, List, Optional

from bpfw.catalog.paths import resolve_blueprint_path
from bpfw.integrations.planner_impl.connection_detection import detect_connections
from bpfw.integrations.planner_impl.connection_merge import merge_connections
from bpfw.integrations.planner_impl.models import (
    PlannerBox,
    PlannerConnection,
    PlannerInterface,
    PlannerInterfaceInput,
    PlannerInterfaceOutput,
    PlannerProjectConfig,
    PlannerSecurityConfig,
    PlannerState,
)
from bpfw.integrations.planner_impl.utils import get_project_defaults, to_snake_case


class BlueprintStateLoader:
    """Load blueprint.yaml into PlannerState or create new state."""
    
    @staticmethod
    def load(project_root: Path) -> PlannerState:
        """Load blueprint state from project.
        
        Args:
            project_root: Root directory of the project.
        
        Returns:
            PlannerState with loaded or default configuration.
        """
        blueprint_path = resolve_blueprint_path(project_root)
        
        if not blueprint_path.exists():
            return BlueprintStateLoader._create_new_state(project_root, blueprint_path)
        
        return BlueprintStateLoader._load_existing_blueprint(project_root, blueprint_path)
    
    @staticmethod
    def _create_new_state(project_root: Path, blueprint_path: Path) -> PlannerState:
        """Create a new planner state with defaults.
        
        Args:
            project_root: Root directory of the project.
            blueprint_path: Path where blueprint.yaml should be created.
        
        Returns:
            New PlannerState with defaults.
        """
        defaults = get_project_defaults(project_root)
        
        project_config = PlannerProjectConfig(
            project_id=defaults["project_id"],
            project_name=defaults["project_name"],
            language=defaults["language"],
            source_roots=defaults["source_roots"],
        )
        
        return PlannerState(
            project_config=project_config,
            blueprint_path=blueprint_path,
            source_mode="new_plan",
        )
    
    @staticmethod
    def _load_existing_blueprint(project_root: Path, blueprint_path: Path) -> PlannerState:
        """Load existing blueprint.yaml into PlannerState.
        
        Args:
            project_root: Root directory of the project.
            blueprint_path: Path to existing blueprint.yaml.
        
        Returns:
            PlannerState loaded from existing blueprint.
        """
        try:
            import yaml
        except ImportError:
            raise ImportError("PyYAML is required but not installed")
        
        with open(blueprint_path, "r", encoding="utf-8") as f:
            blueprint_data = yaml.safe_load(f)
        
        # Load project configuration
        project_config = BlueprintStateLoader._load_project_config(blueprint_data)
        
        # Load boxes from responsibilities
        boxes = BlueprintStateLoader._load_boxes(blueprint_data)
        
        # Load connections from related_code
        blueprint_connections = BlueprintStateLoader._load_connections(blueprint_data, boxes)
        inferred_connections = detect_connections(
            boxes=boxes,
            project_root=project_root,
            source_roots=project_config.source_roots,
            ignored_paths=project_config.ignored_paths,
        )
        connections = merge_connections(
            blueprint_connections=blueprint_connections,
            inferred_connections=inferred_connections,
        )
        
        return PlannerState(
            project_config=project_config,
            boxes=boxes,
            connections=connections,
            blueprint_path=blueprint_path,
            source_mode="existing_blueprint",
        )
    
    @staticmethod
    def _load_project_config(blueprint_data: Dict[str, Any]) -> PlannerProjectConfig:
        """Load project configuration from blueprint data.
        
        Args:
            blueprint_data: The parsed blueprint.yaml data.
        
        Returns:
            PlannerProjectConfig instance.
        """
        project = blueprint_data.get("project", {})
        policy = blueprint_data.get("policy", {})
        security_data = policy.get("security", {})
        
        security = PlannerSecurityConfig(
            no_secrets_in_blueprint=security_data.get("no_secrets_in_blueprint", True),
            public_safe_mode=security_data.get("public_safe_mode", True),
            detected_detail_level=security_data.get("detected_detail_level", "minimal"),
        )
        
        return PlannerProjectConfig(
            project_id=project.get("id", "unknown"),
            project_name=project.get("name", "unknown"),
            root=project.get("root", "."),
            language=project.get("language", "python"),
            source_roots=project.get("source_roots", ["src"]),
            ignored_paths=project.get("ignored_paths", [
                ".git", ".venv", "venv", "__pycache__", "node_modules", "tests", "migrations"
            ]),
            policy_mode=policy.get("mode", "catalog"),
            empty_blueprint_allows_execution=policy.get("empty_blueprint_allows_execution", True),
            defined_blueprint_blocks_on_drift=policy.get("defined_blueprint_blocks_on_drift", True),
            allowed_lifecycles=policy.get("allowed_lifecycles", [
                "active", "experimental", "legacy", "deprecated"
            ]),
            single_active_per_intent=policy.get("single_active_per_intent", True),
            undeclared_code_blocks=policy.get("undeclared_code_blocks", True),
            missing_declared_code_blocks=policy.get("missing_declared_code_blocks", True),
            security=security,
        )
    
    @staticmethod
    def _load_boxes(blueprint_data: Dict[str, Any]) -> List[PlannerBox]:
        """Load boxes from responsibilities section.
        
        Args:
            blueprint_data: The parsed blueprint.yaml data.
        
        Returns:
            List of PlannerBox instances.
        """
        responsibilities = blueprint_data.get("responsibilities", [])
        boxes = []
        
        for resp in responsibilities:
            # Load interface if present
            interface = None
            interface_data = resp.get("interface")
            if interface_data:
                inputs = []
                for input_data in interface_data.get("inputs", []):
                    inputs.append(PlannerInterfaceInput(
                        name=input_data.get("name", ""),
                        type=input_data.get("type"),
                        default=input_data.get("default"),
                        required=input_data.get("required", True),
                        description=input_data.get("description"),
                    ))
                
                output = None
                output_data = interface_data.get("output")
                if output_data:
                    output = PlannerInterfaceOutput(
                        type=output_data.get("type"),
                        description=output_data.get("description"),
                    )
                
                interface = PlannerInterface(inputs=inputs, output=output)
            
            # Get location data
            location = resp.get("location", {})
            
            box = PlannerBox(
                name=resp.get("name", ""),
                domain=resp.get("domain", ""),
                intent=resp.get("intent", ""),
                symbol_type=location.get("symbol_type", "class"),
                lifecycle=resp.get("lifecycle", "active"),
                path=location.get("path"),
                symbol=location.get("symbol"),
                interface=interface,
                notes=resp.get("notes"),
            )
            
            # Override derived fields from blueprint if present
            if "id" in resp:
                box.id = resp["id"]
            
            if location.get("module"):
                box.module = location.get("module")
            
            if location.get("detected", {}).get("qualified_name"):
                box.qualified_name = location.get("detected", {}).get("qualified_name")
            
            if resp.get("duplicate_policy", {}).get("group"):
                box.duplicate_group = resp.get("duplicate_policy", {}).get("group")
            
            boxes.append(box)
        
        return boxes
    
    @staticmethod
    def _load_connections(blueprint_data: Dict[str, Any], boxes: List[PlannerBox]) -> List[PlannerConnection]:
        """Load connections from related_code sections.
        
        Args:
            blueprint_data: The parsed blueprint.yaml data.
            boxes: List of loaded boxes for ID mapping.
        
        Returns:
            List of PlannerConnection instances.
        """
        responsibilities = blueprint_data.get("responsibilities", [])
        connections = []
        
        box_ids = {box.id for box in boxes}

        for resp in responsibilities:
            resp_id = resp.get("id")
            related_code = resp.get("related_code", [])
            
            for rel in related_code:
                target_id = rel.get("target")
                relationship = rel.get("relationship")
                
                if (
                    resp_id
                    and target_id
                    and relationship
                    and resp_id in box_ids
                    and target_id in box_ids
                ):
                    connections.append(PlannerConnection(
                        source_box_id=resp_id,
                        target_box_id=target_id,
                        relationship=relationship,
                        source_kind="blueprint",
                        confidence="high",
                        evidence=["declared:related_code"],
                        status="accepted",
                        notes=rel.get("notes"),
                    ))
        
        return connections
