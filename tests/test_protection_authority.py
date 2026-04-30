import os
from pathlib import Path

import pytest

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
