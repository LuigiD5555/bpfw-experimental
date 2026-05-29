"""Authority index for BPFW root blueprint.yaml."""

from pathlib import Path
from typing import Any

from bpfw.core.catalog.access_control import ensure_blueprint_can_be_written
from bpfw.core.authority.errors import InvalidAuthorityIndexError
from bpfw.core.yaml_io import dump_yaml_data, load_yaml_text


class AuthorityIndex:
    """Represent the root blueprint.yaml authority index.

    The root blueprint.yaml is an index file that contains:
    - version
    - project
    - policy
    - authority
    - includes

    It must NOT contain blocks.
    """

    def __init__(self, path: Path, data: dict[str, Any]) -> None:
        """Initialize the authority index.

        Args:
            path: Path to the blueprint.yaml file.
            data: Parsed YAML data from the blueprint.yaml file.

        Raises:
            InvalidAuthorityIndexError: If the index is invalid.
        """
        self.path = path
        self.data = data
        self._validate()

    def _validate(self) -> None:
        """Validate the authority index structure.

        Raises:
            InvalidAuthorityIndexError: If validation fails.
        """
        if not isinstance(self.data, dict):
            raise InvalidAuthorityIndexError(
                f"Blueprint index must be a dictionary, got {type(self.data).__name__}"
            )

        # Validate authority section
        authority = self.data.get("authority")
        if authority is None:
            raise InvalidAuthorityIndexError(
                "Blueprint index must contain an 'authority' section"
            )

        if not isinstance(authority, dict):
            raise InvalidAuthorityIndexError(
                "Blueprint 'authority' section must be a dictionary"
            )

        # Validate layout
        layout = authority.get("layout")
        if layout != "sharded":
            raise InvalidAuthorityIndexError(
                f"Blueprint authority layout must be 'sharded', got '{layout}'"
            )

        # Validate includes
        includes = self.data.get("includes")
        if includes is None:
            raise InvalidAuthorityIndexError(
                "Blueprint index must contain an 'includes' section"
            )

        if not isinstance(includes, list):
            raise InvalidAuthorityIndexError(
                "Blueprint 'includes' section must be a list"
            )

        if not includes:
            raise InvalidAuthorityIndexError(
                "Blueprint 'includes' section must not be empty"
            )

        # Validate no blocks in root index
        if "blocks" in self.data:
            raise InvalidAuthorityIndexError(
                "Root blueprint.yaml must not contain 'blocks'. "
                "Blocks must be in shard files."
            )

        # Validate no glob includes
        for include_path in includes:
            if not isinstance(include_path, str):
                raise InvalidAuthorityIndexError(
                    f"Include path must be a string, got {type(include_path).__name__}"
                )
            if "*" in include_path or "?" in include_path or "[" in include_path:
                raise InvalidAuthorityIndexError(
                    f"Include path must not use glob patterns: {include_path}"
                )

    @classmethod
    def load(cls, project_root: Path) -> "AuthorityIndex":
        """Load the authority index from the project root.

        Args:
            project_root: The project root directory.

        Returns:
            Loaded AuthorityIndex instance.

        Raises:
            InvalidAuthorityIndexError: If the index cannot be loaded or is invalid.
            FileNotFoundError: If the blueprint.yaml does not exist.
        """
        blueprint_path = project_root / "bpfw" / "blueprint.yaml"

        if not blueprint_path.exists():
            raise FileNotFoundError(
                f"Blueprint index not found: {blueprint_path}"
            )

        try:
            with open(blueprint_path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as error:
            raise InvalidAuthorityIndexError(
                f"Failed to read blueprint index: {error}"
            ) from error

        if not content.strip():
            raise InvalidAuthorityIndexError(
                f"Blueprint index is empty: {blueprint_path}"
            )

        try:
            data = load_yaml_text(content)
        except Exception as error:
            raise InvalidAuthorityIndexError(
                f"Invalid YAML in blueprint index: {error}"
            ) from error

        return cls(path=blueprint_path, data=data)

    def save(self, project_root: Path) -> None:
        """Save the authority index to the project root.

        Args:
            project_root: The project root directory.

        Raises:
            InvalidAuthorityIndexError: If the index is invalid or cannot be saved.
        """
        # Re-validate before saving
        self._validate()

        blueprint_path = project_root / "bpfw" / "blueprint.yaml"
        ensure_blueprint_can_be_written(project_root=project_root)

        # Ensure directory exists
        blueprint_path.parent.mkdir(parents=True, exist_ok=True)

        # Write YAML
        rendered = dump_yaml_data(self.data, sort_keys=False, allow_unicode=True)

        try:
            blueprint_path.write_text(rendered, encoding="utf-8")
        except OSError as error:
            raise InvalidAuthorityIndexError(
                f"Failed to write blueprint index: {error}"
            ) from error

    def get_includes(self) -> list[Path]:
        """Get the list of included shard paths.

        Returns:
            List of project-relative shard paths.
        """
        includes = self.data.get("includes", [])
        return [Path(include_path) for include_path in includes if isinstance(include_path, str)]

    def add_include(self, shard_path: Path) -> None:
        """Add a shard to the includes list.

        Args:
            shard_path: Project-relative path to the shard file.
        """
        includes = self.data.setdefault("includes", [])
        shard_str = str(shard_path)

        if shard_str not in includes:
            includes.append(shard_str)

    def remove_include(self, shard_path: Path) -> None:
        """Remove a shard from the includes list.

        Args:
            shard_path: Project-relative path to the shard file.
        """
        includes = self.data.get("includes", [])
        shard_str = str(shard_path)

        if shard_str in includes:
            includes.remove(shard_str)

    def get_authority_config(self) -> dict[str, Any]:
        """Get the authority configuration.

        Returns:
            Dictionary containing authority configuration.
        """
        authority = self.data.get("authority", {})
        if not isinstance(authority, dict):
            return {}

        return authority
