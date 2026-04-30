from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path


@dataclass(slots=True)
class UnlockWindow:
    resource_id: str
    resource_path: str
    scope: str
    operation: str
    expires_at: str
    granted_by: str
    request_id: str
    grant_id: str


@dataclass(slots=True)
class AuthorityState:
    protection_enabled: bool
    os_lock_enabled: bool
    active_unlock_window: UnlockWindow | None
    last_relock_at: str


def _state_path(project_root: Path) -> Path:
    return project_root / ".bpfw/state.json"


def _default_state() -> AuthorityState:
    return AuthorityState(
        protection_enabled=True,
        os_lock_enabled=False,
        active_unlock_window=None,
        last_relock_at="",
    )


def _window_from_dict(payload: dict[str, str]) -> UnlockWindow:
    return UnlockWindow(
        resource_id=str(payload.get("resource_id", "")),
        resource_path=str(payload.get("resource_path", "")),
        scope=str(payload.get("scope", "")),
        operation=str(payload.get("operation", "")),
        expires_at=str(payload.get("expires_at", "")),
        granted_by=str(payload.get("granted_by", "")),
        request_id=str(payload.get("request_id", "")),
        grant_id=str(payload.get("grant_id", "")),
    )


def _window_to_dict(window: UnlockWindow | None) -> dict[str, str] | None:
    if window is None:
        return None
    return {
        "resource_id": window.resource_id,
        "resource_path": window.resource_path,
        "scope": window.scope,
        "operation": window.operation,
        "expires_at": window.expires_at,
        "granted_by": window.granted_by,
        "request_id": window.request_id,
        "grant_id": window.grant_id,
    }


def load_authority_state(project_root: Path) -> AuthorityState:
    state_path = _state_path(project_root=project_root)
    if not state_path.exists():
        return _default_state()
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return _default_state()
    unlock_window_raw = payload.get("active_unlock_window")
    unlock_window = None
    if isinstance(unlock_window_raw, dict):
        unlock_window = _window_from_dict({str(key): str(value) for key, value in unlock_window_raw.items()})
    return AuthorityState(
        protection_enabled=bool(payload.get("protection_enabled", True)),
        os_lock_enabled=bool(payload.get("os_lock_enabled", False)),
        active_unlock_window=unlock_window,
        last_relock_at=str(payload.get("last_relock_at", "")),
    )


def save_authority_state(project_root: Path, state: AuthorityState) -> Path:
    state_path = _state_path(project_root=project_root)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "protection_enabled": state.protection_enabled,
        "os_lock_enabled": state.os_lock_enabled,
        "active_unlock_window": _window_to_dict(state.active_unlock_window),
        "last_relock_at": state.last_relock_at,
    }
    state_path.write_text(f"{json.dumps(payload, indent=2, ensure_ascii=True)}\n", encoding="utf-8")
    return state_path


def set_unlock_window(project_root: Path, window: UnlockWindow) -> Path:
    state = load_authority_state(project_root=project_root)
    state.active_unlock_window = window
    return save_authority_state(project_root=project_root, state=state)


def clear_unlock_window(project_root: Path, mark_locked: bool = True) -> Path:
    state = load_authority_state(project_root=project_root)
    state.active_unlock_window = None
    if mark_locked:
        state.os_lock_enabled = True
    state.last_relock_at = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
    return save_authority_state(project_root=project_root, state=state)
