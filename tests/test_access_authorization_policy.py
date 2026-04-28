from __future__ import annotations

from pathlib import Path

from bpfw.access.request_store import AccessRequestStore
from bpfw.access.service import AccessService


def _create_request(project_root: Path) -> str:
    request = AccessService().create_request(
        project_root=project_root,
        resource_id="blueprint",
        operation="add_file",
        scope="core",
        reason="Need scoped change",
    )
    return request.request_id


def test_access_grant_blocks_dummy_backend_in_protected_by_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("BPFW_ENV", raising=False)
    monkeypatch.setenv("BPFW_AUTH_BACKEND", "dummy")
    monkeypatch.setenv("BPFW_ACCESS_HMAC_KEY", "test-secret")

    request_id = _create_request(project_root=tmp_path)

    try:
        AccessService().grant_request(
            project_root=tmp_path,
            request_id=request_id,
            granted_by="",
            duration_minutes=30,
        )
    except ValueError as error:
        message = str(error)
    else:
        raise AssertionError("Expected protected mode to block dummy backend")

    assert message == (
        "BLOCK\n\n"
        "No secure authorization backend configured.\n\n"
        "Dummy access grants are only allowed in development mode.\n\n"
        "Set:\n"
        "BPFW_ENV=dev\n\n"
        "Or configure:\n"
        "BPFW_AUTH_BACKEND=sudo"
    )
    stored_request = AccessRequestStore().load(project_root=tmp_path, request_id=request_id)
    assert stored_request.status == "pending"


def test_access_grant_allows_dummy_backend_in_dev(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BPFW_ENV", "dev")
    monkeypatch.setenv("BPFW_AUTH_BACKEND", "dummy")
    monkeypatch.setenv("BPFW_ACCESS_HMAC_KEY", "test-secret")

    request_id = _create_request(project_root=tmp_path)
    grant = AccessService().grant_request(
        project_root=tmp_path,
        request_id=request_id,
        granted_by="",
        duration_minutes=30,
    )

    assert grant.request_id == request_id
