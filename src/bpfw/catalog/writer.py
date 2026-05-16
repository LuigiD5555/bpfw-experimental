"""Blueprint writer for BPFW MVP Catalog Mode initial blueprint generation."""

from pathlib import Path
from typing import Any, Dict, List

from bpfw.catalog.access_control import (
    ensure_blueprint_can_be_written,
    has_temporary_blueprint_unlock_authorization,
)
from bpfw.catalog.status import ALLOWED_STATUSES
from bpfw.catalog.models import DiscoveredCodeUnit
from bpfw.catalog.paths import resolve_blueprint_path
from bpfw.catalog.symbol_types import normalize_symbol_type
from bpfw.core.errors import BlueprintLockedError
from bpfw.protection.setup import format_init_setup_summary, run_protection_setup
from bpfw.protection.authority import (
    get_authority_protection_status,
    lock_authority,
    unlock_authority,
)
from bpfw.shared.text import to_snake_case


def build_initial_blueprint(
    project_root: Path,
    source_roots: List[str],
    ignored_paths: List[str],
    discovered_units: List[DiscoveredCodeUnit],
) -> Dict[str, Any]:
    """Build initial blueprint data from project structure and discovered units.
    
    Args:
        project_root: Root directory of the project.
        allow_unprotected: Whether init may succeed without OS authority protection.
        source_roots: List of source root directories.
        ignored_paths: List of ignored path patterns.
        discovered_units: List of discovered code units.
    
    Returns:
        Dictionary containing blueprint data.
    """
    project_directory_name = project_root.name
    project_id = to_snake_case(project_directory_name)
    
    blocks = []
    for unit in discovered_units:
        normalized_symbol_type = normalize_symbol_type(unit.symbol_type)
        block = {
            "id": to_snake_case(unit.symbol),
            "purpose": None,
            "name": unit.symbol,
            "domain": None,
            "status": None,
            "code": {
                "path": unit.path,
                "module": unit.module,
                "symbol": unit.symbol,
                "kind": normalized_symbol_type,
                "start_line": unit.start_line,
                "end_line": unit.end_line,
            },
            "detected": {
                "qualified_name": unit.qualified_name,
                "kind": normalized_symbol_type,
                "methods": unit.methods,
                "functions": unit.functions,
            },
            "entrypoints": [],
            "connections": [],
            "uniqueness": {
                "group": None,
                "allow_multiple_non_active": True,
                "forbid_active_duplicates": True,
                "suspected_duplicates": [],
            },
            "replacement": {
                "replaces": None,
                "replaced_by": None,
                "reason": None,
            },
            "notes": None,
        }

        # Add interface metadata if available
        if unit.interface_inputs or unit.interface_output:
            interface_data = {}
            if unit.interface_inputs:
                interface_data["inputs"] = unit.interface_inputs
            if unit.interface_output:
                interface_data["output"] = unit.interface_output
            if interface_data:
                block["interface"] = interface_data

        blocks.append(block)
    
    blueprint_data = {
        "version": 1,
        "project": {
            "id": project_id,
            "name": project_directory_name,
            "root": ".",
            "language": "python",
            "source_roots": source_roots,
            "ignored_paths": ignored_paths,
        },
        "policy": {
            "mode": "catalog",
            "empty_blueprint_allows_execution": True,
            "defined_blueprint_blocks_on_drift": True,
            "allowed_statuses": list(ALLOWED_STATUSES),
            "one_active_block_per_purpose": True,
            "undeclared_code_blocks": True,
            "missing_declared_code_blocks": True,
            "security": {
                "no_secrets_in_blueprint": True,
                "public_safe_mode": True,
                "detected_detail_level": "minimal",
            },
        },
        "blocks": blocks,
    }
    
    return blueprint_data


def write_blueprint(blueprint_path: Path, blueprint_data: Dict[str, Any]) -> None:
    """Write blueprint data to YAML file.
    
    Args:
        blueprint_path: Path to the blueprint file.
        blueprint_data: Blueprint data to write.
    """
    try:
        import yaml
    except ImportError:
        raise ImportError("PyYAML is required but not installed")
    
    project_root = blueprint_path.parent.parent
    lock_state = get_authority_protection_status(project_root=project_root).status
    requires_temporary_unlock = lock_state in {"locked", "degraded"}
    temporarily_unlocked = False

    if requires_temporary_unlock and not has_temporary_blueprint_unlock_authorization():
        ensure_blueprint_can_be_written(project_root=project_root)

    if requires_temporary_unlock and has_temporary_blueprint_unlock_authorization():
        unlock_result = unlock_authority(project_root=project_root)
        if unlock_result.status != "unlocked":
            raise BlueprintLockedError(
                "Blueprint is locked and temporary unlock failed. Run bpfw unlock before editing authority data."
            )
        temporarily_unlocked = True

    blueprint_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = yaml.safe_dump(blueprint_data, sort_keys=False, allow_unicode=True)
    try:
        blueprint_path.write_text(rendered, encoding="utf-8")
    except PermissionError as error:
        raise BlueprintLockedError(
            "Blueprint write failed due to OS-level permission protection."
        ) from error
    finally:
        if temporarily_unlocked:
            relock_result = lock_authority(project_root=project_root)
            if relock_result.status not in {"locked", "degraded"}:
                raise BlueprintLockedError(
                    "Blueprint was written, but automatic re-lock failed. "
                    f"Current lock status: {relock_result.status}."
                )


BLUEPRINT_RELATIVE_PATH = "bpfw/blueprint.yaml"


def run_init(project_root: Path, allow_unprotected: bool = False) -> tuple[bool, str, int]:
    """Run the init command to create initial blueprint.
    
    Args:
        project_root: Root directory of the project.
        allow_unprotected: Whether init may succeed without OS authority protection.
    
    Returns:
        Tuple of (success, message, exit_code).
    """
    from bpfw.catalog.scanner import scan_python_project
    
    blueprint_path = resolve_blueprint_path(project_root)
    
    # Step 3: If blueprint already exists, do not overwrite
    if blueprint_path.exists():
        setup_result = run_protection_setup(project_root=project_root, allow_unprotected=allow_unprotected)
        message = format_init_setup_summary(result=setup_result)
        return setup_result.allowed, message, 0 if setup_result.allowed else 1
    
    # Step 4: Create bpfw directory if missing
    blueprint_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Step 5: Determine source_roots
    source_roots = []
    if (project_root / "src").exists():
        source_roots.append("src")
    if (project_root / "app").exists():
        source_roots.append("app")
    if not source_roots:
        source_roots = ["src", "app"]
    
    # Step 6: Use ignored_paths
    ignored_paths = [
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "tests",
        "migrations",
    ]
    
    # Step 7: Run scan_python_project
    scan_result = scan_python_project(
        project_root=project_root,
        source_roots=source_roots,
        ignored_paths=ignored_paths,
    )
    
    # Step 8: Create blueprint YAML
    blueprint_data = build_initial_blueprint(
        project_root=project_root,
        source_roots=source_roots,
        ignored_paths=ignored_paths,
        discovered_units=scan_result.discovered_units,
    )
    
    # Step 9: Write bpfw/blueprint.yaml
    write_blueprint(blueprint_path=blueprint_path, blueprint_data=blueprint_data)

    setup_result = run_protection_setup(project_root=project_root, allow_unprotected=allow_unprotected)
    
    # Step 10: Print init summary
    total_units = len(scan_result.discovered_units)
    pending_purpose = sum(1 for _ in scan_result.discovered_units)
    pending_lifecycle = sum(1 for _ in scan_result.discovered_units)
    pending_domain = sum(1 for _ in scan_result.discovered_units)
    
    init_summary = f"""BPFW initialized.

Blueprint:
  created: {BLUEPRINT_RELATIVE_PATH}

Project:
  language: python

Detected code units:
  total: {total_units}

Pending fields:
  purpose: {pending_purpose}
  status: {pending_lifecycle}
  domain: {pending_domain}

Next:
  bpfw inspector"""
    
    message = f"{init_summary}\n\n{format_init_setup_summary(result=setup_result)}"
    return setup_result.allowed, message, 0 if setup_result.allowed else 1
