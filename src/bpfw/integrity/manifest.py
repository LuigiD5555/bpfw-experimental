"""Integrity manifest builder and loader."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bpfw.blueprint.loader import BlueprintLoadError, load_blueprint_data
from bpfw.blueprint.models import BlueprintModel
from bpfw.blueprint.validator import validate_blueprint
from bpfw.integrity.hash_provider import compute_sha256, read_file_size
from bpfw.integrity.signer import sign_payload


MANIFEST_RELATIVE_PATH = ".bpfw/manifest.json"
_MANIFEST_VERSION = 1


class IntegrityManifestError(RuntimeError):
    """Raised when manifest creation/loading fails."""


@dataclass(slots=True, frozen=True)
class ProtectedTarget:
    """Single protected target tracked in integrity manifest."""

    path: str
    resource_id: str


@dataclass(slots=True, frozen=True)
class ManifestFileRecord:
    """Single manifest file record."""

    path: str
    resource_id: str
    sha256: str
    size: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "resource_id": self.resource_id,
            "sha256": self.sha256,
            "size": self.size,
        }


@dataclass(slots=True, frozen=True)
class ManifestWriteResult:
    """Output for manifest write operations."""

    manifest_path: Path
    updated_at: str
    file_count: int


def manifest_path(project_root: Path) -> Path:
    """Resolve manifest path for a project."""

    return project_root / MANIFEST_RELATIVE_PATH


def _normalize_repo_path(path_value: str) -> str:
    normalized_path = Path(path_value)
    if normalized_path.is_absolute():
        raise IntegrityManifestError(f"Protected path must be relative: {path_value}")
    if any(part == ".." for part in normalized_path.parts):
        raise IntegrityManifestError(f"Protected path cannot contain '..': {path_value}")
    return normalized_path.as_posix()


def _collect_locked_targets(blueprint: BlueprintModel | None) -> dict[str, str]:
    locked_targets: dict[str, str] = {}
    if blueprint is None:
        return locked_targets

    for locked_resource in blueprint.locked_resources:
        if locked_resource.mutability != "locked":
            continue
        locked_targets[_normalize_repo_path(locked_resource.path)] = locked_resource.resource_id
    return locked_targets


def _load_locked_targets_lenient(project_root: Path) -> dict[str, str]:
    try:
        _, payload = load_blueprint_data(project_root=project_root)
    except BlueprintLoadError:
        return {}

    locked_resources = payload.get("locked_resources")
    if not isinstance(locked_resources, list):
        return {}

    locked_targets: dict[str, str] = {}
    for locked_resource in locked_resources:
        if not isinstance(locked_resource, dict):
            continue
        if str(locked_resource.get("mutability", "")).strip() != "locked":
            continue
        resource_path = str(locked_resource.get("path", "")).strip()
        resource_id = str(locked_resource.get("resource_id", "")).strip()
        if not resource_path or not resource_id:
            continue
        if Path(resource_path).is_absolute() or ".." in Path(resource_path).parts:
            continue
        locked_targets[Path(resource_path).as_posix()] = resource_id
    return locked_targets


def _critical_framework_targets(project_root: Path) -> dict[str, str]:
    critical_root = project_root / "src/bpfw"
    if not critical_root.exists():
        return {}

    critical_targets: dict[str, str] = {}
    for file_path in sorted(critical_root.rglob("*")):
        if not file_path.is_file():
            continue
        if "__pycache__" in file_path.parts:
            continue
        if file_path.suffix in {".pyc", ".pyo"}:
            continue
        relative_path = file_path.relative_to(project_root).as_posix()
        critical_targets[relative_path] = f"critical::{relative_path.replace('/', '::')}"
    return critical_targets


def _expand_targets(project_root: Path, targets: dict[str, str]) -> list[ProtectedTarget]:
    expanded_targets: dict[str, str] = {}
    for relative_path, resource_id in targets.items():
        project_path = project_root / relative_path
        if project_path.is_dir():
            for nested_file in sorted(project_path.rglob("*")):
                if nested_file.is_file():
                    nested_relative_path = nested_file.relative_to(project_root).as_posix()
                    expanded_targets[nested_relative_path] = resource_id
            continue

        expanded_targets[relative_path] = resource_id

    return [
        ProtectedTarget(path=path_value, resource_id=expanded_targets[path_value])
        for path_value in sorted(expanded_targets)
    ]


def resolve_protected_targets(project_root: Path, require_valid_blueprint: bool) -> list[ProtectedTarget]:
    """Resolve all files that must be protected by integrity manifest."""

    locked_targets: dict[str, str]
    if require_valid_blueprint:
        validation_result = validate_blueprint(project_root=project_root)
        if not validation_result.is_valid or validation_result.blueprint is None:
            first_error = validation_result.errors[0]
            raise IntegrityManifestError(first_error.message)
        locked_targets = _collect_locked_targets(validation_result.blueprint)
    else:
        locked_targets = _load_locked_targets_lenient(project_root=project_root)

    required_targets: dict[str, str] = {
        "blueprint.yaml": "project_blueprint",
        "architecture.yaml": "architecture_profile",
    }
    required_targets.update(locked_targets)
    required_targets.update(_critical_framework_targets(project_root=project_root))

    return _expand_targets(project_root=project_root, targets=required_targets)


def _build_file_records(project_root: Path, targets: list[ProtectedTarget]) -> list[ManifestFileRecord]:
    records: list[ManifestFileRecord] = []

    for target in targets:
        absolute_path = project_root / target.path
        if not absolute_path.exists():
            raise IntegrityManifestError(f"Protected file is missing: {target.path}")
        if not absolute_path.is_file():
            raise IntegrityManifestError(f"Protected path must be a file: {target.path}")

        records.append(
            ManifestFileRecord(
                path=target.path,
                resource_id=target.resource_id,
                sha256=compute_sha256(absolute_path),
                size=read_file_size(absolute_path),
            )
        )

    return records


def write_manifest(project_root: Path) -> ManifestWriteResult:
    """Generate and persist a signed integrity manifest."""

    protected_targets = resolve_protected_targets(project_root=project_root, require_valid_blueprint=True)
    file_records = _build_file_records(project_root=project_root, targets=protected_targets)

    updated_at = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
    payload_without_signature: dict[str, Any] = {
        "version": _MANIFEST_VERSION,
        "updated_at": updated_at,
        "files": [record.to_dict() for record in file_records],
    }
    signed_manifest = {
        **payload_without_signature,
        "signature": sign_payload(payload_without_signature, project_root=project_root),
    }

    output_path = manifest_path(project_root=project_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{json.dumps(signed_manifest, indent=2, ensure_ascii=True)}\n", encoding="utf-8")

    return ManifestWriteResult(
        manifest_path=output_path,
        updated_at=updated_at,
        file_count=len(file_records),
    )


def load_manifest(project_root: Path) -> dict[str, Any]:
    """Load persisted integrity manifest JSON document."""

    input_path = manifest_path(project_root=project_root)
    if not input_path.exists():
        raise IntegrityManifestError(
            f"Integrity manifest does not exist: {MANIFEST_RELATIVE_PATH}. Run `bpfw manifest write`."
        )

    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise IntegrityManifestError(f"Invalid JSON in integrity manifest: {error}") from error

    if not isinstance(payload, dict):
        raise IntegrityManifestError("Integrity manifest root must be a JSON object")

    return payload
