"""Scope resolution from blueprint resources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bpfw.blueprint.models import BlueprintModel
from bpfw.blueprint.validator import validate_blueprint


class ScopeResolutionError(RuntimeError):
    """Raised when a change scope cannot be resolved from blueprint."""


@dataclass(slots=True, frozen=True)
class ScopeResolution:
    """Resolved scope data used to initialize workspace and policy."""

    resource_id: str
    resource_type: str
    locked: bool
    owner: str
    allowed_files: list[str]
    forbidden_duplicates: list[str]


@dataclass(slots=True, frozen=True)
class LockedResourceIndex:
    """Lookup index for locked resources by path and id."""

    by_path: dict[str, str]
    by_id: dict[str, str]


def _load_blueprint(project_root: Path) -> BlueprintModel:
    validation_result = validate_blueprint(project_root=project_root)
    if not validation_result.is_valid or validation_result.blueprint is None:
        first_error = validation_result.errors[0]
        raise ScopeResolutionError(first_error.message)
    return validation_result.blueprint


def build_locked_resource_index(project_root: Path) -> LockedResourceIndex:
    """Build locked resource indexes from blueprint model."""

    blueprint = _load_blueprint(project_root=project_root)
    path_index: dict[str, str] = {}
    id_index: dict[str, str] = {}

    for locked_resource in blueprint.locked_resources:
        if locked_resource.mutability != "locked":
            continue
        id_index[locked_resource.resource_id] = locked_resource.path
        path_index[locked_resource.path] = locked_resource.resource_id

    return LockedResourceIndex(by_path=path_index, by_id=id_index)


def resolve_scope(project_root: Path, scope_resource_id: str) -> ScopeResolution:
    """Resolve scope against responsibility_id or locked resource_id."""

    normalized_scope_id = scope_resource_id.strip()
    if not normalized_scope_id:
        raise ScopeResolutionError("Scope resource id cannot be empty")

    blueprint = _load_blueprint(project_root=project_root)

    for responsibility in blueprint.responsibilities:
        if responsibility.responsibility_id != normalized_scope_id:
            continue
        allowed_files = sorted({file_path for file_path in responsibility.allowed_files})
        return ScopeResolution(
            resource_id=responsibility.responsibility_id,
            resource_type="responsibility",
            locked=responsibility.mutability == "locked",
            owner=responsibility.owner,
            allowed_files=allowed_files,
            forbidden_duplicates=sorted({value for value in responsibility.forbidden_duplicates}),
        )

    for locked_resource in blueprint.locked_resources:
        if locked_resource.resource_id != normalized_scope_id:
            continue
        return ScopeResolution(
            resource_id=locked_resource.resource_id,
            resource_type="locked_resource",
            locked=locked_resource.mutability == "locked",
            owner=locked_resource.owner,
            allowed_files=[locked_resource.path],
            forbidden_duplicates=[],
        )

    raise ScopeResolutionError(f"Scope `{normalized_scope_id}` does not exist in blueprint")
