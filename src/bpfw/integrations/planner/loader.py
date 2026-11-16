"""Blueprint state loader for the Planner integration."""

from pathlib import Path

from bpfw.core.catalog.domain import BlueprintRepository
from bpfw.core.catalog.paths import resolve_blueprint_path
from bpfw.integrations.planner.factory import PlannerStateFactory
from bpfw.integrations.planner.models import PlannerState


class BlueprintStateLoader:
    """Load blueprint.yaml into PlannerState or create new state."""

    def __init__(self, state_factory: PlannerStateFactory | None = None) -> None:
        """Initialize the planner blueprint loader.

        Args:
            state_factory: Optional factory used to build planner state objects.
        """
        self._state_factory = state_factory or PlannerStateFactory()

    @classmethod
    def load(cls, project_root: Path) -> PlannerState:
        """Load blueprint state from project.

        Args:
            project_root: Root directory of the project.

        Returns:
            PlannerState with loaded or default configuration.
        """
        return cls().load_project(project_root)

    def load_project(self, project_root: Path) -> PlannerState:
        """Load blueprint state using the configured factories.

        Args:
            project_root: Root directory of the project.

        Returns:
            PlannerState with loaded or default configuration.
        """
        blueprint_path = resolve_blueprint_path(project_root)

        if not blueprint_path.exists():
            return self._state_factory.create_new_state(project_root, blueprint_path)

        return self._load_existing_blueprint(project_root, blueprint_path)

    def _load_existing_blueprint(self, project_root: Path, blueprint_path: Path) -> PlannerState:
        """Load existing blueprint.yaml into PlannerState.

        Args:
            project_root: Root directory of the project.
            blueprint_path: Path to existing blueprint.yaml.

        Returns:
            PlannerState loaded from existing blueprint.

        Raises:
            ValueError: If YAML is invalid.
        """
        if blueprint_path.stat().st_size == 0:
            return self._state_factory.create_empty_state(project_root, blueprint_path)

        try:
            repository = BlueprintRepository(project_root=project_root)
            repository_load_result = repository.load()
            blueprint_data = repository_load_result.raw_data
        except Exception as error:
            raise ValueError(
                f"Invalid YAML in {blueprint_path}: {error}\n"
                "Planner cannot overwrite invalid YAML. Fix the file or restore a valid blueprint first."
            ) from error

        if blueprint_data is None:
            return self._state_factory.create_empty_state(project_root, blueprint_path)
        if not isinstance(blueprint_data, dict):
            raise ValueError(
                f"Invalid YAML in {blueprint_path}: root document must be a dictionary."
            )

        return self._state_factory.create_from_blueprint(
            project_root=project_root,
            blueprint_path=blueprint_path,
            blueprint_data=blueprint_data,
        )
