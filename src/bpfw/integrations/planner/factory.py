"""Factories that translate blueprint data into Planner domain models."""

from pathlib import Path
from typing import Any

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


class PlannerProjectConfigFactory:
    """Create planner project configuration objects from blueprint data."""

    def create_from_defaults(self, project_root: Path) -> PlannerProjectConfig:
        """Create planner project configuration from detected project defaults.

        Args:
            project_root: Root directory of the project.

        Returns:
            Project configuration initialized with default values.
        """
        defaults = get_project_defaults(project_root)
        return PlannerProjectConfig(
            project_id=defaults["project_id"],
            project_name=defaults["project_name"],
            language=defaults["language"],
            source_roots=defaults["source_roots"],
        )

    def create_from_blueprint(self, blueprint_data: dict[str, Any]) -> PlannerProjectConfig:
        """Create planner project configuration from parsed blueprint data.

        Args:
            blueprint_data: Parsed blueprint dictionary.

        Returns:
            Project configuration represented by the blueprint.
        """
        project = _dict_or_empty(blueprint_data.get("project"))
        policy = _dict_or_empty(blueprint_data.get("policy"))
        security_data = _dict_or_empty(policy.get("security"))

        security = PlannerSecurityConfig(
            no_secrets_in_blueprint=bool(security_data.get("no_secrets_in_blueprint", True)),
            public_safe_mode=bool(security_data.get("public_safe_mode", True)),
            detected_detail_level=str(security_data.get("detected_detail_level", "minimal")),
        )

        return PlannerProjectConfig(
            project_id=str(project.get("id", "unknown")),
            project_name=str(project.get("name", "unknown")),
            root=str(project.get("root", ".")),
            language=str(project.get("language", "python")),
            source_roots=_string_list(project.get("source_roots"), ["src"]),
            ignored_paths=_string_list(
                project.get("ignored_paths"),
                [".git", ".venv", "venv", "__pycache__", "node_modules", "tests", "migrations"],
            ),
            policy_mode=str(policy.get("mode", "catalog")),
            empty_blueprint_allows_execution=bool(policy.get("empty_blueprint_allows_execution", True)),
            defined_blueprint_blocks_on_drift=bool(policy.get("defined_blueprint_blocks_on_drift", True)),
            allowed_lifecycles=_string_list(
                policy.get("allowed_statuses"),
                ["active", "experimental", "legacy", "deprecated"],
            ),
            single_active_per_purpose=bool(policy.get("one_active_block_per_purpose", True)),
            undeclared_code_blocks=bool(policy.get("undeclared_code_blocks", True)),
            missing_declared_code_blocks=bool(policy.get("missing_declared_code_blocks", True)),
            security=security,
        )


class PlannerInterfaceFactory:
    """Create planner interface models from block interface dictionaries."""

    def create_from_block(self, block_data: dict[str, Any]) -> PlannerInterface | None:
        """Create a planner interface from one blueprint block.

        Args:
            block_data: Blueprint block dictionary.

        Returns:
            Planner interface, or None when the block has no interface section.
        """
        interface_data = block_data.get("interface")
        if not isinstance(interface_data, dict):
            return None

        inputs = [
            PlannerInterfaceInput(
                name=str(input_data.get("name", "")),
                type=input_data.get("type"),
                default=input_data.get("default"),
                required=bool(input_data.get("required", True)),
                description=input_data.get("description"),
            )
            for input_data in interface_data.get("inputs", [])
            if isinstance(input_data, dict)
        ]

        output = None
        output_data = interface_data.get("output")
        if isinstance(output_data, dict):
            output = PlannerInterfaceOutput(
                type=output_data.get("type"),
                description=output_data.get("description"),
            )

        return PlannerInterface(inputs=inputs, output=output)


class PlannerBoxFactory:
    """Create planner box models from blueprint block dictionaries."""

    def __init__(self, interface_factory: PlannerInterfaceFactory | None = None) -> None:
        """Initialize the box factory.

        Args:
            interface_factory: Optional factory used to build block interfaces.
        """
        self._interface_factory = interface_factory or PlannerInterfaceFactory()

    def create_many(self, blueprint_data: dict[str, Any]) -> list[PlannerBox]:
        """Create planner boxes from all blocks in a blueprint.

        Args:
            blueprint_data: Parsed blueprint dictionary.

        Returns:
            Planner boxes for every valid block dictionary.
        """
        blocks = blueprint_data.get("blocks", [])
        if not isinstance(blocks, list):
            return []
        return [
            self.create_from_block(block_data)
            for block_data in blocks
            if isinstance(block_data, dict)
        ]

    def create_from_block(self, block_data: dict[str, Any]) -> PlannerBox:
        """Create one planner box from one blueprint block.

        Args:
            block_data: Blueprint block dictionary.

        Returns:
            Planner box created from the block data.
        """
        code_data = _dict_or_empty(block_data.get("code"))
        box = PlannerBox(
            name=str(block_data.get("name", "")),
            domain=str(block_data.get("domain", "")),
            purpose=str(block_data.get("purpose") or ""),
            symbol_type=str(code_data.get("kind") or "class"),
            lifecycle=str(block_data.get("status") or "active"),
            path=code_data.get("path"),
            symbol=code_data.get("symbol"),
            interface=self._interface_factory.create_from_block(block_data),
            notes=block_data.get("notes"),
        )

        if isinstance(block_data.get("id"), str):
            box.id = block_data["id"]
        if isinstance(code_data.get("module"), str):
            box.module = code_data["module"]

        detected_data = _dict_or_empty(block_data.get("detected"))
        if isinstance(detected_data.get("qualified_name"), str):
            box.qualified_name = detected_data["qualified_name"]

        uniqueness_data = _dict_or_empty(block_data.get("uniqueness"))
        if isinstance(uniqueness_data.get("group"), str):
            box.duplicate_group = uniqueness_data["group"]

        return box


class PlannerConnectionFactory:
    """Create planner connection models from declared block relationships."""

    def create_many(
        self,
        blueprint_data: dict[str, Any],
        boxes: list[PlannerBox],
    ) -> tuple[list[PlannerConnection], list[PlannerConnection]]:
        """Create valid and broken planner connections from blueprint blocks.

        Args:
            blueprint_data: Parsed blueprint dictionary.
            boxes: Planner boxes already created from the same blueprint.

        Returns:
            Tuple containing valid declared connections and broken references.
        """
        blocks = blueprint_data.get("blocks", [])
        if not isinstance(blocks, list):
            return [], []

        box_ids = {box.id for box in boxes}
        connections: list[PlannerConnection] = []
        broken_connections: list[PlannerConnection] = []

        for block_data in blocks:
            if not isinstance(block_data, dict):
                continue
            source_id = block_data.get("id")
            block_connections = block_data.get("connections", [])
            if not isinstance(source_id, str) or not isinstance(block_connections, list):
                continue

            for relationship_data in block_connections:
                if not isinstance(relationship_data, dict):
                    continue
                connection = self.create_from_relationship(
                    source_id=source_id,
                    relationship_data=relationship_data,
                    box_ids=box_ids,
                )
                if connection is None:
                    continue
                if connection.status == "broken":
                    broken_connections.append(connection)
                else:
                    connections.append(connection)

        return connections, broken_connections

    def create_from_relationship(
        self,
        source_id: str,
        relationship_data: dict[str, Any],
        box_ids: set[str],
    ) -> PlannerConnection | None:
        """Create one planner connection from one relationship dictionary.

        Args:
            source_id: Source block identifier.
            relationship_data: Declared connection dictionary.
            box_ids: Existing planner box identifiers.

        Returns:
            Planner connection, or None when the relationship is incomplete.
        """
        target_id = relationship_data.get("target")
        relationship = relationship_data.get("meaning")
        if not isinstance(target_id, str) or not isinstance(relationship, str):
            return None

        status = "accepted" if source_id in box_ids and target_id in box_ids else "broken"
        return PlannerConnection(
            source_box_id=source_id,
            target_box_id=target_id,
            relationship=relationship,
            source_kind="blueprint",
            confidence="high",
            evidence=["declared:connections"],
            status=status,
            notes=relationship_data.get("notes"),
        )


class PlannerStateFactory:
    """Create complete planner state objects from project and blueprint inputs."""

    def __init__(
        self,
        project_config_factory: PlannerProjectConfigFactory | None = None,
        box_factory: PlannerBoxFactory | None = None,
        connection_factory: PlannerConnectionFactory | None = None,
    ) -> None:
        """Initialize the planner state factory.

        Args:
            project_config_factory: Optional project configuration factory.
            box_factory: Optional planner box factory.
            connection_factory: Optional planner connection factory.
        """
        self._project_config_factory = project_config_factory or PlannerProjectConfigFactory()
        self._box_factory = box_factory or PlannerBoxFactory()
        self._connection_factory = connection_factory or PlannerConnectionFactory()

    def create_new_state(self, project_root: Path, blueprint_path: Path) -> PlannerState:
        """Create a new planner state with project defaults.

        Args:
            project_root: Root directory of the project.
            blueprint_path: Path where the blueprint should be stored.

        Returns:
            Planner state initialized for a new plan.
        """
        return PlannerState(
            project_config=self._project_config_factory.create_from_defaults(project_root),
            blueprint_path=blueprint_path,
            source_mode="new_plan",
        )

    def create_empty_state(self, project_root: Path, blueprint_path: Path) -> PlannerState:
        """Create a planner state for an empty blueprint file.

        Args:
            project_root: Root directory of the project.
            blueprint_path: Path to the empty blueprint file.

        Returns:
            Planner state marked as empty blueprint mode.
        """
        state = self.create_new_state(project_root, blueprint_path)
        state.source_mode = "empty_blueprint"
        return state

    def create_from_blueprint(
        self,
        project_root: Path,
        blueprint_path: Path,
        blueprint_data: dict[str, Any],
    ) -> PlannerState:
        """Create planner state from parsed blueprint data.

        Args:
            project_root: Root directory of the project.
            blueprint_path: Path to the loaded blueprint file.
            blueprint_data: Parsed blueprint dictionary.

        Returns:
            Fully assembled planner state.
        """
        project_config = self._project_config_factory.create_from_blueprint(blueprint_data)
        boxes = self._box_factory.create_many(blueprint_data)
        connections, broken_connections = self._connection_factory.create_many(blueprint_data, boxes)
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

        return PlannerState(
            project_config=project_config,
            boxes=boxes,
            connections=all_connections,
            blueprint_path=blueprint_path,
            source_mode="existing_blueprint" if boxes else "empty_blueprint",
            broken_connections=broken_connections,
        )


def _dict_or_empty(value: Any) -> dict[str, Any]:
    """Return the value when it is a dictionary, otherwise return an empty dictionary.

    Args:
        value: Candidate dictionary value.

    Returns:
        Dictionary value or an empty dictionary.
    """
    return value if isinstance(value, dict) else {}


def _string_list(value: Any, default: list[str]) -> list[str]:
    """Return a list of strings from a candidate sequence.

    Args:
        value: Candidate list value.
        default: Fallback list used when value is not a non-empty list.

    Returns:
        Normalized list of strings.
    """
    if not isinstance(value, list) or not value:
        return list(default)
    return [str(item) for item in value]
