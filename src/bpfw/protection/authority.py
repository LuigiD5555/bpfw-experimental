"""Blueprint and guard-file protection authority for BPFW MVP Catalog Mode."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import bpfw
from bpfw.catalog.paths import CANONICAL_BLUEPRINT_FILE
from bpfw.protection.os_lock import get_file_lock_state, lock_file, unlock_file

BLUEPRINT_RESOURCE_TYPE = "blueprint"
GUARD_RESOURCE_TYPE = "guard"
MISSING_BLUEPRINT_STATUS = "missing_blueprint"

_FALLBACK_LOCK_PATH = "bpfw/.lock"


@dataclass(frozen=True)
class ProtectedResource:
    """Represent a file protected by BPFW."""

    path: Path
    resource_type: str
    exists: bool


@dataclass(frozen=True)
class ProtectionResult:
    """Represent the result of a BPFW authority protection operation."""

    operation: str
    blueprint_path: Path
    protected_resources: List[ProtectedResource] = field(default_factory=list)
    skipped_resources: List[ProtectedResource] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    status: str = "unknown"


def resolve_project_blueprint_path(project_root: Path) -> Path:
    """Return the project blueprint authority file path."""

    return project_root / CANONICAL_BLUEPRINT_FILE


def resolve_bpfw_package_root() -> Path:
    """Return the installed BPFW package root directory."""

    return Path(bpfw.__file__).resolve().parent


def resolve_guard_files() -> List[Path]:
    """Return internal BPFW guard files that should be protected."""

    package_root = resolve_bpfw_package_root()
    return [
        package_root / "protection" / "os_lock.py",
        package_root / "protection" / "authority.py",
        package_root / "protection" / "setup.py",
        package_root / "catalog" / "access_control.py",
    ]


def resolve_protected_resources(project_root: Path) -> List[ProtectedResource]:
    """Return all authority and guard files that BPFW lock must protect."""

    blueprint_path = resolve_project_blueprint_path(project_root=project_root)
    resources = [
        ProtectedResource(
            path=blueprint_path,
            resource_type=BLUEPRINT_RESOURCE_TYPE,
            exists=blueprint_path.exists(),
        )
    ]

    for guard_file_path in resolve_guard_files():
        resources.append(
            ProtectedResource(
                path=guard_file_path,
                resource_type=GUARD_RESOURCE_TYPE,
                exists=guard_file_path.exists(),
            )
        )

    return resources


def _resource_lock_identifier(project_root: Path, resource: ProtectedResource) -> str:
    """Return the identifier used by the OS lock marker for a protected resource."""

    if resource.resource_type == BLUEPRINT_RESOURCE_TYPE:
        return CANONICAL_BLUEPRINT_FILE

    return str(resource.path.resolve())


def _write_fallback_lock(project_root: Path) -> None:
    """Write a logical-only lock marker when OS enforcement is unavailable."""

    lock_path = project_root / _FALLBACK_LOCK_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        f"locked: true\nresource: {CANONICAL_BLUEPRINT_FILE}\n",
        encoding="utf-8",
    )


def _remove_fallback_lock(project_root: Path) -> None:
    """Remove the logical-only lock marker if it exists."""

    lock_path = project_root / _FALLBACK_LOCK_PATH
    if lock_path.exists():
        lock_path.unlink()


def _is_fallback_locked(project_root: Path) -> bool:
    """Check whether the fallback logical lock marker is present."""

    lock_path = project_root / _FALLBACK_LOCK_PATH
    if not lock_path.exists():
        return False

    content = lock_path.read_text(encoding="utf-8")
    return "locked: true" in content and CANONICAL_BLUEPRINT_FILE in content


def _missing_blueprint_result(operation: str, blueprint_path: Path) -> ProtectionResult:
    """Build the shared missing-blueprint protection result."""

    return ProtectionResult(
        operation=operation,
        blueprint_path=blueprint_path,
        warnings=["BPFW blueprint does not exist. Run bpfw init first."],
        status=MISSING_BLUEPRINT_STATUS,
    )


def _lock_existing_resource(project_root: Path, resource: ProtectedResource) -> str:
    """Lock one existing resource using the OS lock backend."""

    return lock_file(
        project_root=project_root,
        relative_path=_resource_lock_identifier(project_root=project_root, resource=resource),
    )


def _unlock_existing_resource(project_root: Path, resource: ProtectedResource) -> str:
    """Unlock one existing resource using the OS lock backend."""

    return unlock_file(
        project_root=project_root,
        relative_path=_resource_lock_identifier(project_root=project_root, resource=resource),
    )


def _get_existing_resource_state(project_root: Path, resource: ProtectedResource) -> str:
    """Return the OS lock state for one existing resource."""

    return get_file_lock_state(
        project_root=project_root,
        relative_path=_resource_lock_identifier(project_root=project_root, resource=resource),
    )


def lock_authority(project_root: Path) -> ProtectionResult:
    """Lock the project blueprint and BPFW internal guard files."""

    blueprint_path = resolve_project_blueprint_path(project_root=project_root)
    resources = resolve_protected_resources(project_root=project_root)
    blueprint_resource = resources[0]
    if not blueprint_resource.exists:
        return _missing_blueprint_result(operation="lock", blueprint_path=blueprint_path)

    protected_resources: List[ProtectedResource] = []
    skipped_resources: List[ProtectedResource] = []
    warnings: List[str] = []
    lock_states: list[str] = []

    guard_resources = [
        resource for resource in resources if resource.resource_type == GUARD_RESOURCE_TYPE
    ]
    resources_in_lock_order = [*guard_resources, blueprint_resource]

    for resource in resources_in_lock_order:
        if not resource.exists:
            skipped_resources.append(resource)
            warnings.append(f"Skipped missing guard file: {resource.path}")
            continue

        lock_state = _lock_existing_resource(project_root=project_root, resource=resource)
        lock_states.append(lock_state)
        if lock_state == "locked":
            protected_resources.append(resource)

    if lock_states and all(lock_state == "locked" for lock_state in lock_states):
        status = "locked"
    elif "unsupported" in lock_states:
        status = "unsupported"
    elif "unknown" in lock_states:
        status = "unknown"
    else:
        status = "degraded"

    if status != "locked":
        for protected_resource in reversed(protected_resources):
            _unlock_existing_resource(project_root=project_root, resource=protected_resource)
        _remove_fallback_lock(project_root=project_root)

    return ProtectionResult(
        operation="lock",
        blueprint_path=blueprint_path,
        protected_resources=protected_resources,
        skipped_resources=skipped_resources,
        warnings=warnings,
        status=status,
    )


def unlock_authority(project_root: Path) -> ProtectionResult:
    """Unlock the project blueprint and BPFW internal guard files."""

    blueprint_path = resolve_project_blueprint_path(project_root=project_root)
    resources = resolve_protected_resources(project_root=project_root)
    blueprint_resource = resources[0]
    if not blueprint_resource.exists:
        return _missing_blueprint_result(operation="unlock", blueprint_path=blueprint_path)

    protected_resources: List[ProtectedResource] = []
    skipped_resources: List[ProtectedResource] = []
    warnings: List[str] = []
    unlock_states: list[str] = []

    guard_resources = [
        resource for resource in resources if resource.resource_type == GUARD_RESOURCE_TYPE
    ]
    resources_in_unlock_order = [blueprint_resource, *reversed(guard_resources)]

    for resource in resources_in_unlock_order:
        if not resource.exists:
            skipped_resources.append(resource)
            warnings.append(f"Skipped missing guard file: {resource.path}")
            continue

        unlock_state = _unlock_existing_resource(project_root=project_root, resource=resource)
        unlock_states.append(unlock_state)
        if unlock_state == "unlocked":
            protected_resources.append(resource)

    _remove_fallback_lock(project_root=project_root)

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
    """Return the protection status for the blueprint and guard files."""

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
            warnings.append(f"Skipped missing guard file: {resource.path}")
            continue

        lock_state = _get_existing_resource_state(project_root=project_root, resource=resource)
        resource_states.append((resource, lock_state))
        if lock_state == "locked":
            protected_resources.append(resource)

    blueprint_state = resource_states[0][1] if resource_states else "unknown"
    guard_states = [
        lock_state
        for resource, lock_state in resource_states
        if resource.resource_type == GUARD_RESOURCE_TYPE
    ]

    if blueprint_state == "locked" and not skipped_resources and all(
        guard_state == "locked" for guard_state in guard_states
    ):
        status = "locked"
    elif blueprint_state == "locked":
        status = "degraded"
    elif blueprint_state == "unlocked":
        status = "unlocked"
    else:
        status = "unknown"

    if blueprint_state != "locked" and _is_fallback_locked(project_root=project_root):
        _remove_fallback_lock(project_root=project_root)

    return ProtectionResult(
        operation="status",
        blueprint_path=blueprint_path,
        protected_resources=protected_resources,
        skipped_resources=skipped_resources,
        warnings=warnings,
        status=status,
    )


def setup_blueprint_protection(project_root: Path) -> str:
    """Prepare full authority protection as the hidden compatibility path."""

    return lock_authority(project_root=project_root).status


def lock_blueprint(project_root: Path) -> str:
    """Lock the project blueprint and BPFW internal guard files."""

    return lock_authority(project_root=project_root).status


def unlock_blueprint(project_root: Path) -> str:
    """Unlock the project blueprint and BPFW internal guard files."""

    return unlock_authority(project_root=project_root).status


def get_blueprint_lock_state(project_root: Path) -> str:
    """Return the full authority protection state for compatibility callers."""

    status = get_authority_protection_status(project_root=project_root).status
    if status == MISSING_BLUEPRINT_STATUS:
        return "unknown"
    return status
