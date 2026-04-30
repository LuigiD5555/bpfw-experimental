"""Project initialization detector for MVP catalog mode."""

from dataclasses import dataclass
from pathlib import Path

from bpfw.blueprint.schema import CANONICAL_BLUEPRINT_FILE, LEGACY_BLUEPRINT_FILE

_IGNORED_ROOTS = {".venv", ".git", ".bpfw", "build", "dist", "__pycache__"}


@dataclass(slots=True)
class ProjectDetectionResult:
    """Represents the detected initialization state of a project."""

    project_root: Path
    has_blueprint: bool
    has_manifest: bool
    has_source_files: bool
    is_initialized: bool
    is_existing_project: bool


class ProjectDetector:
    """Detects whether a project is new, existing, or already initialized."""

    def detect(self, project_root: Path) -> ProjectDetectionResult:
        """Inspect the project root and return its initialization state."""

        has_blueprint = (project_root / CANONICAL_BLUEPRINT_FILE).exists() or (project_root / LEGACY_BLUEPRINT_FILE).exists()
        has_manifest = (project_root / ".bpfw/manifest.json").exists()
        has_source_files = self._has_python_sources(project_root=project_root)
        is_initialized = has_blueprint
        is_existing_project = has_source_files and not is_initialized

        return ProjectDetectionResult(
            project_root=project_root,
            has_blueprint=has_blueprint,
            has_manifest=has_manifest,
            has_source_files=has_source_files,
            is_initialized=is_initialized,
            is_existing_project=is_existing_project,
        )

    def _has_python_sources(self, project_root: Path) -> bool:
        for python_file_path in project_root.rglob("*.py"):
            if any(part in _IGNORED_ROOTS for part in python_file_path.parts):
                continue
            return True
        return False
