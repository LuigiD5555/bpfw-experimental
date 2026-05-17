from pathlib import Path

import pytest

from bpfw.core.errors import BlueprintLockedError
from bpfw.protection import runtime_lease


def test_inspector_auto_approves_temporary_unlock_when_locked(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_lease,
        "get_authority_protection_status",
        lambda project_root: type("ProtectionStatus", (), {"status": "locked"})(),
    )
    monkeypatch.setattr(runtime_lease, "_is_interactive_terminal", lambda: False)
    prompt_called = {"value": False}

    def fake_prompt(tool_name: str, input_func) -> bool:
        prompt_called["value"] = True
        return False

    monkeypatch.setattr(runtime_lease, "_prompt_unlock_confirmation", fake_prompt)

    with runtime_lease.runtime_blueprint_write_lease(
        project_root=tmp_path,
        tool_name="inspector",
    ) as lease:
        assert lease.temporarily_unlocked is True

    assert prompt_called["value"] is False


def test_planner_still_requires_interactive_terminal_when_locked(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_lease,
        "get_authority_protection_status",
        lambda project_root: type("ProtectionStatus", (), {"status": "locked"})(),
    )
    monkeypatch.setattr(runtime_lease, "_is_interactive_terminal", lambda: False)

    with pytest.raises(BlueprintLockedError, match="non-interactive"):
        with runtime_lease.runtime_blueprint_write_lease(
            project_root=tmp_path,
            tool_name="planner",
        ):
            pass
