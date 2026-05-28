"""PURPOSE blueprint state loader for the Planner tool
DOMAIN  planner workflow
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from bpfw.core.catalog.domain import BlueprintRepository
from bpfw.core.catalog.paths import resolve_blueprint_path
from bpfw.integrations.planner.connection_detection import detect_connections
from bpfw.integrations.planner.connection_merge import merge_connections
from bpfw.integrations.planner.models import (
    PlannerBox,
    PlannerConnection,
    PlannerInterface,
    PlannerInterfaceInput,
    PlannerInterfaceOutput,
    PlannerProjectConfig,
    PlannerSecurityConfig,
    PlannerState,
)
from bpfw.integrations.planner.utils import get_project_defaults


class BlueprintStateLoader:
    """PURPOSE read blueprint.yaml into PlannerState or create new state
    DOMAIN  planner workflow
    """

    @staticmethod
    def load(project_root: Path) -> PlannerState:
        """PURPOSE read blueprint state from project
        DOMAIN  planner workflow
        """
        blueprint_path = resolve_blueprint_path(project_root)

        if not blueprint_path.exists():
            return BlueprintStateLoader._create_new_state(project_root, blueprint_path)

        return BlueprintStateLoader._load_existing_blueprint(project_root, blueprint_path)

    @staticmethod
    def _create_new_state(project_root: Path, blueprint_path: Path) -> PlannerState:
        """PURPOSE create a new planner state with defaults
        DOMAIN  planner workflow
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
        """PURPOSE read blueprint.yaml into PlannerState
        DOMAIN  planner workflow
        """
        # Check if file is empty
        if blueprint_path.stat().st_size == 0:
            state = BlueprintStateLoader._create_new_state(project_root, blueprint_path)
            state.source_mode = "empty_blueprint"
            return state

        try:
            repository = BlueprintRepository(project_root=project_root)
            repository_load_result = repository.load()
            blueprint_data = repository_load_result.raw_data
        except Exception as e:
            raise ValueError(
                f"Invalid YAML in {blueprint_path}: {e}\n"
                f"Planner cannot overwrite invalid YAML. Fix the file or restore a valid blueprint first."
            )

        # Check if blueprint_data is None (empty file with comments only)
        if blueprint_data is None:
            state = BlueprintStateLoader._create_new_state(project_root, blueprint_path)
            state.source_mode = "empty_blueprint"
            return state

        # Load project configuration
        project_config = BlueprintStateLoader._load_project_config(blueprint_data)

        # Load boxes from blocks
        boxes = BlueprintStateLoader._load_boxes(blueprint_data)

        # Load connections from block connections (and detect broken ones)
        connections, broken_connections = BlueprintStateLoader._load_connections(blueprint_data, boxes)

        # Merge with inferred connections
        inferred_connections = detect_connections(
            boxes=boxes,
            project_root=project_root,
            source_roots=project_config.source_roots,
            ignored_paths=project_config.ignored_paths,
        )
        all_connections = merge_connections(
            blueprint_connections=connections,
            inferred_connections=inferred_connections,
        )

        source_mode = "existing_blueprint"
        if not boxes:
            source_mode = "empty_blueprint"

        return PlannerState(
            project_config=project_config,
            boxes=boxes,
            connections=all_connections,
            blueprint_path=blueprint_path,
            source_mode=source_mode,
            broken_connections=broken_connections,
        )

    @staticmethod
    def _load_project_config(blueprint_data: Dict[str, Any]) -> PlannerProjectConfig:
        """PURPOSE read project configuration from blueprint data
        DOMAIN  planner workflow
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
            allowed_lifecycles=[str(status) for status in policy.get("allowed_statuses", ["active", "experimental", "legacy", "deprecated"])],
            single_active_per_purpose=bool(policy.get("one_active_block_per_purpose", True)),
            undeclared_code_blocks=policy.get("undeclared_code_blocks", True),
            missing_declared_code_blocks=policy.get("missing_declared_code_blocks", True),
            security=security,
        )

    @staticmethod
    def _load_boxes(blueprint_data: Dict[str, Any]) -> List[PlannerBox]:
        """PURPOSE read boxes from blocks section
        DOMAIN  planner workflow
        """
        blocks = blueprint_data.get("blocks", [])
        boxes = []

        for resp in blocks:
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

            # Get code data
            code = resp.get("code", {})
            if not isinstance(code, dict):
                code = {}

            box = PlannerBox(
                name=resp.get("name", ""),
                domain=resp.get("domain", ""),
                purpose=resp.get("purpose") or "",
                symbol_type=code.get("kind") or "class",
                lifecycle=resp.get("status") or "active",
                path=code.get("path"),
                symbol=code.get("symbol"),
                interface=interface,
                notes=resp.get("notes"),
            )

            # Override derived fields from blueprint if present
            if "id" in resp:
                box.id = resp["id"]

            if code.get("module"):
                box.module = code.get("module")

            detected = resp.get("detected", {})
            if isinstance(detected, dict) and detected.get("qualified_name"):
                box.qualified_name = detected.get("qualified_name")

            uniqueness = resp.get("uniqueness", {})
            if not isinstance(uniqueness, dict):
                uniqueness = {}
            if uniqueness.get("group"):
                box.duplicate_group = uniqueness.get("group")

            boxes.append(box)

        return boxes

    @staticmethod
    def _load_connections(blueprint_data: Dict[str, Any], boxes: List[PlannerBox]) -> tuple[List[PlannerConnection], List[PlannerConnection]]:
        """PURPOSE read connections from block connections sections
        DOMAIN  planner workflow
        """
        blocks = blueprint_data.get("blocks", [])
        connections = []
        broken_connections = []

        box_ids = {box.id for box in boxes}

        for resp in blocks:
            resp_id = resp.get("id")
            block_connections = resp.get("connections", [])
            if not isinstance(block_connections, list):
                block_connections = []

            for rel in block_connections:
                target_id = rel.get("target")
                relationship = rel.get("meaning") if isinstance(rel, dict) else None

                if not resp_id or not target_id or not relationship:
                    continue

                # Check if both source and target exist
                if resp_id not in box_ids or target_id not in box_ids:
                    # This is a broken connection (orphan reference)
                    broken_connections.append(PlannerConnection(
                        source_box_id=resp_id,
                        target_box_id=target_id,
                        relationship=relationship,
                        source_kind="blueprint",
                        confidence="high",
                        evidence=["declared:connections"],
                        status="broken",
                        notes=rel.get("notes"),
                    ))
                else:
                    connections.append(PlannerConnection(
                        source_box_id=resp_id,
                        target_box_id=target_id,
                        relationship=relationship,
                        source_kind="blueprint",
                        confidence="high",
                        evidence=["declared:connections"],
                        status="accepted",
                        notes=rel.get("notes"),
                    ))

        return connections, broken_connections
