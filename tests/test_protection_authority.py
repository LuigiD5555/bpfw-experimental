import os
from pathlib import Path

import pytest

import bpfw.protection.authority as authority
import bpfw.protection.os_lock as os_lock
from bpfw.catalog.access_control import ensure_blueprint_can_be_written
from bpfw.core.errors import BlueprintLockedError
from bpfw.protection.authority import get_blueprint_lock_state, lock_blueprint, unlock_blueprint

RUNS_AS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


def test_blueprint_lock_flow_uses_os_lock(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text("version: 1\nresponsibilities: []\n", encoding="utf-8")

    assert get_blueprint_lock_state(project_root=tmp_path) == "unlocked"
    assert lock_blueprint(project_root=tmp_path) == "locked"
    assert get_blueprint_lock_state(project_root=tmp_path) == "locked"
    assert unlock_blueprint(project_root=tmp_path) == "unlocked"


def test_access_control_blocks_locked_blueprint(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text("version: 1\nresponsibilities: []\n", encoding="utf-8")
    lock_blueprint(project_root=tmp_path)

    try:
        ensure_blueprint_can_be_written(project_root=tmp_path)
    except BlueprintLockedError as error:
        message = str(error)
    else:
        raise AssertionError("Expected locked blueprint write to be blocked")

    assert message == "Blueprint is locked. Run bpfw unlock before editing."


@pytest.mark.skipif(RUNS_AS_ROOT, reason="root can bypass POSIX write bits")
def test_locked_blueprint_rejects_direct_file_write(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text("version: 1\nresponsibilities: []\n", encoding="utf-8")

    lock_blueprint(project_root=tmp_path)

    try:
        with pytest.raises(PermissionError):
            blueprint_path.write_text("version: 2\nresponsibilities: []\n", encoding="utf-8")
    finally:
        unlock_blueprint(project_root=tmp_path)

    blueprint_path.write_text("version: 2\nresponsibilities: []\n", encoding="utf-8")
    assert blueprint_path.read_text(encoding="utf-8").startswith("version: 2")


def test_lock_blueprint_does_not_claim_os_lock_when_backend_is_unsupported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text("version: 1\nresponsibilities: []\n", encoding="utf-8")

    fallback_lock_path = tmp_path / "bpfw" / ".lock"
    fallback_lock_path.write_text(
        "locked: true\nresource: bpfw/blueprint.yaml\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(authority, "lock_file", lambda project_root, relative_path: "unsupported")

    assert lock_blueprint(project_root=tmp_path) == "unsupported"
    assert get_blueprint_lock_state(project_root=tmp_path) == "unlocked"
    assert not fallback_lock_path.exists()


@pytest.mark.parametrize(
    ("platform_name", "expected_strategy_name"),
    [
        ("linux", "PosixLockStrategy"),
        ("linux2", "PosixLockStrategy"),
        ("darwin", "PosixLockStrategy"),
        ("win32", "WindowsLockStrategy"),
        ("freebsd14", "UnsupportedLockStrategy"),
    ],
)
def test_lock_strategy_selection_uses_platform_specific_backend(
    platform_name: str,
    expected_strategy_name: str,
) -> None:
    strategy = os_lock._build_lock_strategy(platform_name=platform_name)
    assert strategy.__class__.__name__ == expected_strategy_name
