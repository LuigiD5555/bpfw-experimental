"""PURPOSE blueprint and guard-file protection authority for BPFW catalog mode
DOMAIN  framework core
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import bpfw
from bpfw.core.catalog.paths import CANONICAL_BLUEPRINT_FILE
from bpfw.core.protection.os_lock import (
    DEGRADED,
    LOCKED,
    get_project_file_lock_state,
    lock_project_file,
    unlock_project_file,
)

BLUEPRINT_RESOURCE_TYPE = "blueprint"
AUTHORITY_DIRECTORY_RESOURCE_TYPE = "authority_directory"
SHARD_RESOURCE_TYPE = "shard"
GUARD_RESOURCE_TYPE = "guard"
MISSING_BLUEPRINT_STATUS = "missing_blueprint"


@dataclass(frozen=True)
class ProtectedResource:
    """PURPOSE store information about a file protected by BPFW
    DOMAIN  framework core
    """

    path: Path
    resource_type: str
    exists: bool


@dataclass(frozen=True)
class ProtectionResult:
    """PURPOSE store information about the result of a BPFW authority protection operation
    DOMAIN  framework core
    """

    operation: str
    blueprint_path: Path
    protected_resources: List[ProtectedResource] = field(default_factory=list)
    skipped_resources: List[ProtectedResource] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    status: str = "unknown"


def resolve_project_blueprint_path(project_root: Path) -> Path:
    """PURPOSE get the project blueprint authority file path
    DOMAIN  framework core
    """

    return project_root / CANONICAL_BLUEPRINT_FILE


def resolve_bpfw_package_root() -> Path:
    """PURPOSE get the installed BPFW package root directory
    DOMAIN  framework core
    """

    return Path(bpfw.__file__).resolve().parent


def resolve_guard_files() -> List[Path]:
    """PURPOSE get paths to BPFW package files that implement the protection mechanism
    DOMAIN  framework core
    """

    package_root = resolve_bpfw_package_root()
    return [
        package_root / "core" / "protection" / "os_lock.py",
        package_root / "core" / "protection" / "authority.py",
        package_root / "core" / "protection" / "setup.py",
        package_root / "core" / "catalog" / "access_control.py",
    ]


def resolve_protected_resources(project_root: Path) -> List[ProtectedResource]:
    """PURPOSE build the full protection resource list for a project, including its blueprint and BPFW guard files
    DOMAIN  framework core
    """

    bpfw_directory = project_root / "bpfw"
    blueprint_path = resolve_project_blueprint_path(project_root=project_root)
    resources = [
        ProtectedResource(
            path=blueprint_path,
            resource_type=BLUEPRINT_RESOURCE_TYPE,
            exists=blueprint_path.exists(),
        )
    ]
    resources.extend(_resolve_shard_resources(project_root=project_root, blueprint_path=blueprint_path))

    for guard_file_path in resolve_guard_files():
        resources.append(
            ProtectedResource(
                path=guard_file_path,
                resource_type=GUARD_RESOURCE_TYPE,
                exists=guard_file_path.exists(),
            )
        )

    return resources


def _resolve_shard_resources(project_root: Path, blueprint_path: Path) -> List[ProtectedResource]:
    """PURPOSE get shard resources declared by the authority index
    DOMAIN  framework core
    """

    if not blueprint_path.exists():
        return []

    try:
        import yaml
    except ImportError:
        return []

    try:
        data = yaml.safe_load(blueprint_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []

    if not isinstance(data, dict):
        return []
    includes = data.get("includes", [])
    if not isinstance(includes, list):
        return []

    resources: List[ProtectedResource] = []
    seen_paths: set[Path] = set()
    for include_path in includes:
        if not isinstance(include_path, str) or not include_path.strip():
            continue
        shard_path = project_root / include_path
        if shard_path in seen_paths:
            continue
        seen_paths.add(shard_path)
        resources.append(
            ProtectedResource(
                path=shard_path,
                resource_type=SHARD_RESOURCE_TYPE,
                exists=shard_path.exists(),
            )
        )
    return resources


def _missing_blueprint_result(operation: str, blueprint_path: Path) -> ProtectionResult:
    """PURPOSE build the shared missing-blueprint protection result
    DOMAIN  framework core
    """

    return ProtectionResult(
        operation=operation,
        blueprint_path=blueprint_path,
        warnings=["BPFW blueprint does not exist. Run bpfw init first."],
        status=MISSING_BLUEPRINT_STATUS,
    )


def _lock_existing_resource(project_root: Path, resource: ProtectedResource) -> str:
    """PURPOSE lock one resource using the OS lock backend
    DOMAIN  framework core
    """

    return lock_project_file(project_root=project_root, path=resource.path)


def _unlock_existing_resource(project_root: Path, resource: ProtectedResource) -> str:
    """PURPOSE unlock one resource using the OS lock backend
    DOMAIN  framework core
    """

    return unlock_project_file(project_root=project_root, path=resource.path)


def _get_existing_resource_state(project_root: Path, resource: ProtectedResource) -> str:
    """PURPOSE get the OS lock state for one resource
    DOMAIN  framework core
    """

    return get_project_file_lock_state(project_root=project_root, path=resource.path)


def lock_authority(project_root: Path) -> ProtectionResult:
    """PURPOSE lock the project blueprint and BPFW internal guard files
    DOMAIN  framework core
    """

    blueprint_path = resolve_project_blueprint_path(project_root=project_root)
    resources = resolve_protected_resources(project_root=project_root)
    blueprint_resource = resources[0]
    if not blueprint_resource.exists:
        return _missing_blueprint_result(operation="lock", blueprint_path=blueprint_path)

    protected_resources: List[ProtectedResource] = []
    skipped_resources: List[ProtectedResource] = []
    warnings: List[str] = []
    lock_states: list[str] = []

    guard_resources = [resource for resource in resources if resource.resource_type == GUARD_RESOURCE_TYPE]
    shard_resources = [resource for resource in resources if resource.resource_type == SHARD_RESOURCE_TYPE]
    resources_in_lock_order = [
        *guard_resources,
        blueprint_resource,
        *shard_resources,
    ]

    for resource in resources_in_lock_order:
        if not resource.exists:
            skipped_resources.append(resource)
            warnings.append(f"Skipped missing {resource.resource_type}: {resource.path}")
            continue

        lock_state = _lock_existing_resource(project_root=project_root, resource=resource)
        lock_states.append(lock_state)
        if lock_state in {LOCKED, DEGRADED}:
            protected_resources.append(resource)

    if lock_states and all(lock_state == LOCKED for lock_state in lock_states):
        status = LOCKED
    elif "unsupported" in lock_states:
        status = "unsupported"
    elif "unknown" in lock_states:
        status = "unknown"
    elif lock_states and all(lock_state in {LOCKED, DEGRADED} for lock_state in lock_states):
        status = DEGRADED
    else:
        status = DEGRADED

    if status in {"unsupported", "unknown"}:
        for protected_resource in reversed(protected_resources):
            _unlock_existing_resource(project_root=project_root, resource=protected_resource)

    return ProtectionResult(
        operation="lock",
        blueprint_path=blueprint_path,
        protected_resources=protected_resources,
        skipped_resources=skipped_resources,
        warnings=warnings,
        status=status,
    )


def unlock_authority(project_root: Path) -> ProtectionResult:
    """PURPOSE unlock the project blueprint and BPFW internal guard files
    DOMAIN  framework core
    """

    blueprint_path = resolve_project_blueprint_path(project_root=project_root)
    resources = resolve_protected_resources(project_root=project_root)
    blueprint_resource = resources[0]
    if not blueprint_resource.exists:
        return _missing_blueprint_result(operation="unlock", blueprint_path=blueprint_path)

    protected_resources: List[ProtectedResource] = []
    skipped_resources: List[ProtectedResource] = []
    warnings: List[str] = []
    unlock_states: list[str] = []

    guard_resources = [resource for resource in resources if resource.resource_type == GUARD_RESOURCE_TYPE]
    shard_resources = [resource for resource in resources if resource.resource_type == SHARD_RESOURCE_TYPE]
    resources_in_unlock_order = [
        blueprint_resource,
        *shard_resources,
        *reversed(guard_resources),
    ]

    for resource in resources_in_unlock_order:
        if not resource.exists:
            skipped_resources.append(resource)
            warnings.append(f"Skipped missing {resource.resource_type}: {resource.path}")
            continue

        unlock_state = _unlock_existing_resource(project_root=project_root, resource=resource)
        unlock_states.append(unlock_state)
        if unlock_state == "unlocked":
            protected_resources.append(resource)

    if unlock_states and all(unlock_state == "unlocked" for unlock_state in unlock_states):
        status = "unlocked"
    elif "unsupported" in unlock_states:
        status = "unsupported"
    elif "unknown" in unlock_states:
        status = "unknown"
    else:
        status = "degraded"

    return ProtectionResult(
        operation="unlock",
        blueprint_path=blueprint_path,
        protected_resources=protected_resources,
        skipped_resources=skipped_resources,
        warnings=warnings,
        status=status,
    )


def get_authority_protection_status(project_root: Path) -> ProtectionResult:
    """PURPOSE get the protection status for the blueprint and guard files
    DOMAIN  framework core
    """

    blueprint_path = resolve_project_blueprint_path(project_root=project_root)
    resources = resolve_protected_resources(project_root=project_root)
    blueprint_resource = resources[0]
    if not blueprint_resource.exists:
        return _missing_blueprint_result(operation="status", blueprint_path=blueprint_path)

    protected_resources: List[ProtectedResource] = []
    skipped_resources: List[ProtectedResource] = []
    warnings: List[str] = []
    resource_states: list[tuple[ProtectedResource, str]] = []

    for resource in resources:
        if not resource.exists:
            skipped_resources.append(resource)
            warnings.append(f"Skipped missing {resource.resource_type}: {resource.path}")
            continue

        lock_state = _get_existing_resource_state(project_root=project_root, resource=resource)
        resource_states.append((resource, lock_state))
        if lock_state in {LOCKED, DEGRADED}:
            protected_resources.append(resource)

    lock_states = [lock_state for _resource, lock_state in resource_states]
    if lock_states and all(lock_state == LOCKED for lock_state in lock_states):
        status = LOCKED
    elif lock_states and all(lock_state in {LOCKED, DEGRADED} for lock_state in lock_states):
        status = DEGRADED
    elif any(lock_state in {LOCKED, DEGRADED} for lock_state in lock_states):
        status = DEGRADED
    elif lock_states and all(lock_state == "unlocked" for lock_state in lock_states):
        status = "unlocked"
    else:
        status = "unknown"

    return ProtectionResult(
        operation="status",
        blueprint_path=blueprint_path,
        protected_resources=protected_resources,
        skipped_resources=skipped_resources,
        warnings=warnings,
        status=status,
    )
