"""Executable catalog loader and validator."""

from dataclasses import dataclass
import importlib
from pathlib import Path

import yaml

from bpfw.catalog.catalog_paths import get_repo_root


class ExecutableCatalogError(RuntimeError):
    """Raised when executable catalog is invalid."""


@dataclass(frozen=True)
class ExecutableDefinition:
    executable_id: str
    kind: str
    target: str
    owner: str


def _catalog_directory() -> Path:
    return get_repo_root() / "src" / "catalog" / "executables"


def _load_yaml_documents() -> list[dict[str, object]]:
    catalog_directory = _catalog_directory()
    if not catalog_directory.exists() or not catalog_directory.is_dir():
        raise ExecutableCatalogError(f"Executable catalog directory not found: {catalog_directory}")

    yaml_files = sorted(catalog_directory.glob("*.yaml"))
    if not yaml_files:
        raise ExecutableCatalogError(f"No executable catalog yaml files found in: {catalog_directory}")

    documents: list[dict[str, object]] = []
    for yaml_file in yaml_files:
        with yaml_file.open(encoding="utf-8") as file_handle:
            raw_document = yaml.safe_load(file_handle)
        if not isinstance(raw_document, dict):
            raise ExecutableCatalogError(f"Invalid YAML object in {yaml_file}")
        documents.append(raw_document)
    return documents


def load_executable_catalog() -> tuple[ExecutableDefinition, ...]:
    definitions: list[ExecutableDefinition] = []
    for document in _load_yaml_documents():
        required_fields = ("executable_id", "kind", "target", "owner")
        missing_fields = [field for field in required_fields if field not in document]
        if missing_fields:
            raise ExecutableCatalogError(
                f"Executable document missing fields {missing_fields}: {document}"
            )
        definitions.append(
            ExecutableDefinition(
                executable_id=str(document["executable_id"]),
                kind=str(document["kind"]),
                target=str(document["target"]),
                owner=str(document["owner"]),
            )
        )

    unique_ids = {definition.executable_id for definition in definitions}
    if len(unique_ids) != len(definitions):
        raise ExecutableCatalogError("Duplicate executable_id detected in executable catalog.")
    return tuple(definitions)


def _resolve_target_path(target: str) -> Path:
    return get_repo_root() / target


def validate_executable_catalog() -> list[str]:
    """Validate executable catalog entries and return error messages."""
    errors: list[str] = []
    for definition in load_executable_catalog():
        if definition.kind in {"shell_script", "python_script", "systemd_unit", "compose_file"}:
            target_path = _resolve_target_path(definition.target)
            if not target_path.exists():
                errors.append(
                    f"{definition.executable_id}: target path does not exist: {definition.target}"
                )
            continue

        if definition.kind == "python_module":
            try:
                importlib.import_module(definition.target)
                continue
            except Exception:
                pass
            module_path = definition.target.replace(".", "/")
            root = get_repo_root()
            module_file = root / f"{module_path}.py"
            module_package = root / module_path
            if not module_file.exists() and not module_package.exists():
                errors.append(
                    f"{definition.executable_id}: python module target not found: {definition.target}"
                )
            continue

        errors.append(
            f"{definition.executable_id}: unsupported executable kind: {definition.kind}"
        )

    return errors


def check_executables_main() -> int:
    """CLI entrypoint for executable catalog checks."""
    try:
        errors = validate_executable_catalog()
    except ExecutableCatalogError as catalog_error:
        print(f"ERROR: {catalog_error}")
        return 1

    if errors:
        print("Executable catalog violations found:")
        for error in errors:
            print(f"  {error}")
        return 1

    print("Executable catalog is valid.")
    return 0
