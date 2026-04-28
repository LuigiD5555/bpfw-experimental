"""Change session persistence for start/review/apply lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from bpfw.change.scope import ScopeResolution
from bpfw.change.store import ChangeStoreError, ensure_directory, read_json, write_json


CHANGES_RELATIVE_PATH = ".bpfw/changes"
WORKSPACES_RELATIVE_PATH = ".bpfw/workspaces"


class ChangeSessionError(RuntimeError):
    """Raised for invalid or missing change session operations."""


@dataclass(slots=True)
class ChangeSession:
    """Mutable change session state persisted in .bpfw/changes."""

    change_id: str
    scope_resource_id: str
    scope_type: str
    scope_locked: bool
    owner: str
    allowed_files: list[str]
    forbidden_duplicates: list[str]
    workspace_relative_path: str
    status: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "change_id": self.change_id,
            "scope_resource_id": self.scope_resource_id,
            "scope_type": self.scope_type,
            "scope_locked": self.scope_locked,
            "owner": self.owner,
            "allowed_files": self.allowed_files,
            "forbidden_duplicates": self.forbidden_duplicates,
            "workspace_relative_path": self.workspace_relative_path,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }



def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


def change_root(project_root: Path) -> Path:
    """Resolve root directory for session state."""

    return project_root / CHANGES_RELATIVE_PATH


def workspace_path_for_change(project_root: Path, change_id: str) -> Path:
    """Resolve workspace path for a change id."""

    return project_root / WORKSPACES_RELATIVE_PATH / change_id


def session_file_path(project_root: Path, change_id: str) -> Path:
    """Resolve session JSON file path."""

    return change_root(project_root=project_root) / change_id / "session.json"


def save_change_session(project_root: Path, session: ChangeSession) -> None:
    """Persist session state."""

    try:
        write_json(path=session_file_path(project_root=project_root, change_id=session.change_id), payload=session.to_dict())
    except ChangeStoreError as error:
        raise ChangeSessionError(str(error)) from error


def create_change_session(project_root: Path, change_id: str, scope: ScopeResolution) -> ChangeSession:
    """Create a new change session for workspace flow."""

    normalized_change_id = change_id.strip()
    if not normalized_change_id:
        raise ChangeSessionError("change_id cannot be empty")

    existing_session_path = session_file_path(project_root=project_root, change_id=normalized_change_id)
    if existing_session_path.exists():
        raise ChangeSessionError(f"Change session already exists: {normalized_change_id}")

    created_at = _now_iso()
    session = ChangeSession(
        change_id=normalized_change_id,
        scope_resource_id=scope.resource_id,
        scope_type=scope.resource_type,
        scope_locked=scope.locked,
        owner=scope.owner,
        allowed_files=list(scope.allowed_files),
        forbidden_duplicates=list(scope.forbidden_duplicates),
        workspace_relative_path=f"{WORKSPACES_RELATIVE_PATH}/{normalized_change_id}",
        status="started",
        created_at=created_at,
        updated_at=created_at,
    )

    ensure_directory(workspace_path_for_change(project_root=project_root, change_id=normalized_change_id).parent)
    save_change_session(project_root=project_root, session=session)
    return session


def load_change_session(project_root: Path, change_id: str) -> ChangeSession:
    """Load change session from .bpfw/changes."""

    try:
        payload = read_json(path=session_file_path(project_root=project_root, change_id=change_id))
    except ChangeStoreError as error:
        raise ChangeSessionError(str(error)) from error

    required_fields = (
        "change_id",
        "scope_resource_id",
        "scope_type",
        "scope_locked",
        "owner",
        "allowed_files",
        "forbidden_duplicates",
        "workspace_relative_path",
        "status",
        "created_at",
        "updated_at",
    )
    for field_name in required_fields:
        if field_name not in payload:
            raise ChangeSessionError(f"Change session missing field `{field_name}`")

    allowed_files = payload["allowed_files"]
    forbidden_duplicates = payload["forbidden_duplicates"]
    if not isinstance(allowed_files, list) or not all(isinstance(value, str) for value in allowed_files):
        raise ChangeSessionError("Change session allowed_files must be a list of strings")
    if not isinstance(forbidden_duplicates, list) or not all(
        isinstance(value, str) for value in forbidden_duplicates
    ):
        raise ChangeSessionError("Change session forbidden_duplicates must be a list of strings")

    return ChangeSession(
        change_id=str(payload["change_id"]),
        scope_resource_id=str(payload["scope_resource_id"]),
        scope_type=str(payload["scope_type"]),
        scope_locked=bool(payload["scope_locked"]),
        owner=str(payload["owner"]),
        allowed_files=allowed_files,
        forbidden_duplicates=forbidden_duplicates,
        workspace_relative_path=str(payload["workspace_relative_path"]),
        status=str(payload["status"]),
        created_at=str(payload["created_at"]),
        updated_at=str(payload["updated_at"]),
    )


def update_change_status(project_root: Path, session: ChangeSession, status: str) -> ChangeSession:
    """Update and persist session status."""

    session.status = status
    session.updated_at = _now_iso()
    save_change_session(project_root=project_root, session=session)
    return session
