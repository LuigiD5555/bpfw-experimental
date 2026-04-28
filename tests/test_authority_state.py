from __future__ import annotations

from pathlib import Path

from bpfw.authority.state import AuthorityState, UnlockWindow, load_authority_state, save_authority_state


def test_authority_state_roundtrip(tmp_path: Path) -> None:
    state = AuthorityState(
        protection_enabled=True,
        os_lock_enabled=True,
        active_unlock_window=UnlockWindow(
            resource_id="project_blueprint",
            resource_path="blueprint.yaml",
            scope="query_execution",
            operation="add_allowed_file",
            expires_at="2026-01-01T00:10:00+00:00",
            granted_by="tester",
            request_id="access-request-001",
            grant_id="access-grant-001",
        ),
        last_relock_at="2026-01-01T00:00:00+00:00",
    )
    save_authority_state(project_root=tmp_path, state=state)
    loaded = load_authority_state(project_root=tmp_path)

    assert loaded.protection_enabled is True
    assert loaded.os_lock_enabled is True
    assert loaded.active_unlock_window is not None
    assert loaded.active_unlock_window.resource_id == "project_blueprint"
    assert loaded.active_unlock_window.operation == "add_allowed_file"
