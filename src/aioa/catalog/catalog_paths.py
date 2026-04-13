"""Catalog path resolution utilities for classic and extended catalogs."""

import os
from pathlib import Path
from typing import List


class CatalogDirectoryNotFoundError(Exception):
    """Raised when the catalog directory does not exist."""

    def __init__(self, expected_path: Path) -> None:
        self.expected_path = expected_path
        super().__init__(
            f"Catalog directory not found at: {expected_path}"
        )


class CatalogFilesNotFoundError(Exception):
    """Raised when no YAML files are found in the catalog directory."""

    def __init__(self, catalog_path: Path) -> None:
        self.catalog_path = catalog_path
        super().__init__(
            f"No YAML files found in catalog directory: {catalog_path}"
        )


def get_repo_root() -> Path:
    """Resolve the repository root directory.

    Uses a marker file (.git) to find the true repository root,
    avoiding fragile cwd-based assumptions.

    Returns:
        Path to the repository root directory.

    Raises:
        RuntimeError: If the repository root cannot be determined.
    """
    explicit_root = os.environ.get("AIOA_PROJECT_ROOT")
    if explicit_root:
        candidate_root = Path(explicit_root).expanduser().resolve()
        catalog_marker = candidate_root / "src" / "catalog" / "responsibilities"
        if catalog_marker.exists() and catalog_marker.is_dir():
            return candidate_root
        raise RuntimeError(
            "AIOA_PROJECT_ROOT is set but does not contain "
            "src/catalog/responsibilities."
        )

    cwd_root = Path.cwd().resolve()
    cwd_marker = cwd_root / "src" / "catalog" / "responsibilities"
    if cwd_marker.exists() and cwd_marker.is_dir():
        return cwd_root

    current = Path(__file__).resolve()

    while current != current.parent:
        git_dir = current / ".git"
        if git_dir.exists():
            return current
        current = current.parent

    current = Path(__file__).resolve()
    while current != current.parent:
        catalog_marker = current / "src" / "catalog" / "responsibilities"
        if catalog_marker.exists() and catalog_marker.is_dir():
            return current
        current = current.parent

    raise RuntimeError(
        "Could not determine repository root. "
        "No .git directory and no src/catalog/responsibilities marker found."
    )


def get_catalog_directory() -> Path:
    """Resolve the catalog responsibilities directory.

    Returns:
        Path to src/catalog/responsibilities.

    Raises:
        CatalogDirectoryNotFoundError: If the directory does not exist.
    """
    repo_root = get_repo_root()
    catalog_path = repo_root / "src" / "catalog" / "responsibilities"

    if not catalog_path.exists():
        raise CatalogDirectoryNotFoundError(catalog_path)

    if not catalog_path.is_dir():
        raise CatalogDirectoryNotFoundError(catalog_path)

    return catalog_path


def _get_catalog_subdirectory(directory_name: str) -> Path:
    repo_root = get_repo_root()
    catalog_subdirectory = repo_root / "src" / "catalog" / directory_name
    if not catalog_subdirectory.exists() or not catalog_subdirectory.is_dir():
        raise CatalogDirectoryNotFoundError(catalog_subdirectory)
    return catalog_subdirectory


def _list_yaml_files_from_directory(directory_path: Path) -> List[Path]:
    yaml_files = sorted(directory_path.glob("*.yaml"))
    if not yaml_files:
        raise CatalogFilesNotFoundError(directory_path)
    return yaml_files


def list_catalog_yaml_files() -> List[Path]:
    """List all YAML files in the catalog directory.

    Returns:
        Sorted list of Path objects for each .yaml file in the catalog.

    Raises:
        CatalogDirectoryNotFoundError: If the catalog directory does not exist.
        CatalogFilesNotFoundError: If no YAML files are found.
    """
    return _list_yaml_files_from_directory(get_catalog_directory())


def list_policy_yaml_files() -> List[Path]:
    return _list_yaml_files_from_directory(_get_catalog_subdirectory("policies"))


def list_contract_yaml_files() -> List[Path]:
    return _list_yaml_files_from_directory(_get_catalog_subdirectory("contracts"))


def list_type_yaml_files() -> List[Path]:
    return _list_yaml_files_from_directory(_get_catalog_subdirectory("types"))


def list_operation_yaml_files() -> List[Path]:
    return _list_yaml_files_from_directory(_get_catalog_subdirectory("operations"))


def list_binding_yaml_files() -> List[Path]:
    return _list_yaml_files_from_directory(_get_catalog_subdirectory("bindings"))


def list_interaction_yaml_files() -> List[Path]:
    return _list_yaml_files_from_directory(_get_catalog_subdirectory("interactions"))
