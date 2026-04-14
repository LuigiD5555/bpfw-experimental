"""Compatibility wrappers for catalog path resolution."""

from pathlib import Path
from typing import List

from bpfw.catalog.catalog_paths import (
    CatalogDirectoryNotFoundError,
    CatalogFilesNotFoundError,
)


def get_repo_root() -> Path:
    from bpfw.catalog.catalog_paths import get_repo_root as core_get_repo_root

    return core_get_repo_root()


def get_catalog_directory() -> Path:
    repo_root = get_repo_root()
    catalog_path = repo_root / "src" / "catalog" / "responsibilities"
    if not catalog_path.exists() or not catalog_path.is_dir():
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
