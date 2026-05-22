"""Blueprint writer for BPFW MVP Catalog Mode initial blueprint generation."""

from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List

from bpfw.catalog.access_control import (
    ensure_blueprint_can_be_written,
    has_temporary_blueprint_unlock_authorization,
)
from bpfw.catalog.paths import (
    DEFAULT_CORE_SHARD,
    resolve_blueprint_path,
    resolve_shard_path,
)
from bpfw.catalog.status import ALLOWED_STATUSES
from bpfw.catalog.models import DiscoveredCodeUnit
from bpfw.catalog.symbol_types import normalize_symbol_type
from bpfw.core.errors import BlueprintLockedError
from bpfw.protection.setup import format_setup_summary, run_protection_setup
from bpfw.protection.authority import (
    get_authority_protection_status,
    lock_authority,
    unlock_authority,
)
from bpfw.shared.text import to_snake_case


class BlockFactory:
    """Centralized factory for creating blueprint block dictionaries.

    Ensures every block has a consistent schema with all required keys,
    avoiding scattered dict-literal construction across the codebase.
    """

    @staticmethod
    def create(
        block_id: str,
        name: str,
        code: Dict[str, Any],
        detected: Dict[str, Any],
        *,
        purpose: Any = None,
        domain: Any = None,
        status: Any = None,
        interface: Dict[str, Any] | None = None,
        entrypoints: List[Any] | None = None,
        connections: List[Any] | None = None,
        uniqueness: Dict[str, Any] | None = None,
        replacement: Dict[str, Any] | None = None,
        notes: Any = None,
    ) -> Dict[str, Any]:
        """Create a fully populated block dictionary.

        Args:
            block_id: Unique block identifier.
            name: Human-readable block name.
            code: Code metadata dict (path, module, symbol, kind, start_line, end_line).
            detected: Detection metadata dict (qualified_name, kind, methods, functions).
            purpose: Block purpose (default None).
            domain: Block domain (default None).
            status: Block status (default None).
            interface: Optional interface metadata.
            entrypoints: Optional entrypoints list.
            connections: Optional connections list.
            uniqueness: Optional uniqueness metadata.
            replacement: Optional replacement metadata.
            notes: Optional notes string.

        Returns:
            Complete block dictionary with all canonical keys.
        """
        block: Dict[str, Any] = {
            "id": block_id,
            "purpose": purpose,
            "name": name,
            "domain": domain,
            "status": status,
            "code": code,
            "detected": detected,
            "entrypoints": entrypoints if entrypoints is not None else [],
            "connections": connections if connections is not None else [],
            "uniqueness": uniqueness if uniqueness is not None else {
                "group": None,
                "allow_multiple_non_active": True,
                "forbid_active_duplicates": True,
                "suspected_duplicates": [],
            },
            "replacement": replacement if replacement is not None else {
                "replaces": None,
                "replaced_by": None,
                "reason": None,
            },
            "notes": notes,
        }

        if interface is not None:
            block["interface"] = interface

        return block


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
        Dictionary containing blueprint index data (without blocks).
    """
    project_directory_name = project_root.name
    project_id = to_snake_case(project_directory_name)
    
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
        "authority": {
            "layout": "sharded",
            "shard_strategy": "domain",
            "default_shard": DEFAULT_CORE_SHARD,
            "allow_empty_shards": False,
            "auto_create_shards": True,
            "remove_empty_shards": False,
        },
        "includes": [DEFAULT_CORE_SHARD],
    }

    return blueprint_data


def build_core_shard(discovered_units: List[DiscoveredCodeUnit]) -> Dict[str, Any]:
    """Build core shard data from discovered units.
    
    Args:
        discovered_units: List of discovered code units.
    
    Returns:
        Dictionary containing shard data with blocks.
    """
    blocks = []
    seen_block_ids: dict[str, int] = {}
    for unit in discovered_units:
        normalized_symbol_type = normalize_symbol_type(unit.symbol_type)
        base_block_id = to_snake_case(f"{unit.module}_{unit.symbol}")
        next_sequence = seen_block_ids.get(base_block_id, 0)
        seen_block_ids[base_block_id] = next_sequence + 1
        block_id = base_block_id if next_sequence == 0 else f"{base_block_id}_{next_sequence + 1}"

        # Build optional interface metadata
        interface_data: Dict[str, Any] | None = None
        if unit.interface_inputs or unit.interface_output:
            interface_data = {}
            if unit.interface_inputs:
                interface_data["inputs"] = unit.interface_inputs
            if unit.interface_output:
                interface_data["output"] = unit.interface_output
            if not interface_data:
                interface_data = None

        block = BlockFactory.create(
            block_id=block_id,
            name=unit.symbol,
            code={
                "path": unit.path,
                "module": unit.module,
                "symbol": unit.symbol,
                "kind": normalized_symbol_type,
                "start_line": unit.start_line,
                "end_line": unit.end_line,
            },
            detected={
                "qualified_name": unit.qualified_name,
                "kind": normalized_symbol_type,
                "methods": unit.methods,
                "functions": unit.functions,
            },
            interface=interface_data,
        )

        blocks.append(block)
    
    shard_data = {"blocks": blocks}
    return shard_data


def _write_shard(shard_path: Path, shard_data: Dict[str, Any], project_root: Path) -> None:
    """Write a shard file to disk.
    
    Args:
        shard_path: Path to the shard file.
        shard_data: Shard data to write.
        project_root: Project root for lock management.
    """
    try:
        import yaml
    except ImportError:
        raise ImportError("PyYAML is required but not installed")
    
    lock_state = get_authority_protection_status(project_root=project_root).status
    requires_temporary_unlock = lock_state in {"locked", "degraded"}
    temporarily_unlocked = False

    ensure_blueprint_can_be_written(project_root=project_root)

    if requires_temporary_unlock and has_temporary_blueprint_unlock_authorization():
        unlock_result = unlock_authority(project_root=project_root)
        if unlock_result.status != "unlocked":
            raise BlueprintLockedError(
                "Blueprint is locked and temporary unlock failed. Run bpfw unlock before editing authority data."
            )
        temporarily_unlocked = True

    shard_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = yaml.safe_dump(shard_data, sort_keys=False, allow_unicode=True)
    try:
        shard_path.write_text(rendered, encoding="utf-8")
    except PermissionError as error:
        raise BlueprintLockedError(
            "Blueprint shard write failed due to OS-level permission protection."
        ) from error
    finally:
        if temporarily_unlocked:
            relock_result = lock_authority(project_root=project_root)
            if relock_result.status not in {"locked", "degraded"}:
                raise BlueprintLockedError(
                    "Blueprint shard was written, but automatic re-lock failed. "
                    f"Current lock status: {relock_result.status}."
                )


def write_blueprint(
    blueprint_path: Path,
    blueprint_data: Dict[str, Any],
    shard_data: Dict[str, Any] | None = None,
) -> None:
    """Write blueprint index and optionally shard data to YAML files.
    
    Args:
        blueprint_path: Path to the blueprint index file.
        blueprint_data: Blueprint index data to write.
        shard_data: Optional shard data to write to default core shard.
    """
    try:
        import yaml
    except ImportError:
        raise ImportError("PyYAML is required but not installed")
    
    project_root = blueprint_path.parent.parent
    
    # Write shard if provided
    if shard_data:
        core_shard_path = resolve_shard_path(project_root, "core.yaml")
        _write_shard(core_shard_path, shard_data, project_root)
    
    lock_state = get_authority_protection_status(project_root=project_root).status
    requires_temporary_unlock = lock_state in {"locked", "degraded"}
    temporarily_unlocked = False

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


def _extract_repair_command(reason: str) -> str | None:
    """Extract ownership repair command from protection setup reason text."""

    marker = "Repair with: "
    if marker not in reason:
        return None
    command = reason.split(marker, maxsplit=1)[1].strip()
    return command or None


def _try_interactive_permission_repair(setup_result) -> bool:  # noqa: ANN001
    """Run ownership repair as an interactive fallback when available."""

    if not sys.stdin.isatty():
        return False
    if setup_result.support is None:
        return False

    repair_command = _extract_repair_command(reason=setup_result.support.reason)
    if repair_command is None:
        return False

    print("BPFW needs elevated permissions to repair project ownership before lock setup.")
    print("This will run:")
    print(f"  {repair_command}")

    command_result = subprocess.run(repair_command, shell=True, check=False)
    return command_result.returncode == 0


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
        if (
            not allow_unprotected
            and not setup_result.allowed
            and setup_result.lock_state == "unsupported"
            and _try_interactive_permission_repair(setup_result=setup_result)
        ):
            setup_result = run_protection_setup(project_root=project_root, allow_unprotected=allow_unprotected)
        message = format_setup_summary(result=setup_result)
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
    
    # Step 8: Create blueprint index YAML
    blueprint_data = build_initial_blueprint(
        project_root=project_root,
        source_roots=source_roots,
        ignored_paths=ignored_paths,
        discovered_units=scan_result.discovered_units,
    )
    
    # Step 9: Create core shard YAML
    shard_data = build_core_shard(discovered_units=scan_result.discovered_units)
    
    # Step 10: Write blueprint index and core shard
    write_blueprint(
        blueprint_path=blueprint_path,
        blueprint_data=blueprint_data,
        shard_data=shard_data,
    )

    setup_result = run_protection_setup(project_root=project_root, allow_unprotected=allow_unprotected)
    if (
        not allow_unprotected
        and not setup_result.allowed
        and setup_result.lock_state == "unsupported"
        and _try_interactive_permission_repair(setup_result=setup_result)
    ):
        setup_result = run_protection_setup(project_root=project_root, allow_unprotected=allow_unprotected)
    
    # Step 11: Print init summary
    total_units = len(scan_result.discovered_units)
    pending_purpose = sum(1 for _ in scan_result.discovered_units)
    pending_lifecycle = sum(1 for _ in scan_result.discovered_units)
    pending_domain = sum(1 for _ in scan_result.discovered_units)
    
    init_summary = f"""BPFW initialized.

Blueprint:
  created: {BLUEPRINT_RELATIVE_PATH}
  shards: {DEFAULT_CORE_SHARD}

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
    
    message = f"{init_summary}\n\n{format_setup_summary(result=setup_result)}"
    return setup_result.allowed, message, 0 if setup_result.allowed else 1
