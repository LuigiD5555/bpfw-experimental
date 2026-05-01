import os
from pathlib import Path

import pytest

import bpfw.protection.authority as authority
import bpfw.protection.os_lock as os_lock
from bpfw.catalog.access_control import ensure_blueprint_can_be_written
from bpfw.core.errors import BlueprintLockedError
from bpfw.protection.authority import (
    get_authority_protection_status,
    get_blueprint_lock_state,
    lock_blueprint,
    resolve_protected_resources,
    unlock_blueprint,
)

RUNS_AS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


def _create_guard_package_root(tmp_path: Path) -> Path:
    package_root = tmp_path / "package" / "bpfw"
    for relative_path in (
        "protection/os_lock.py",
        "protection/authority.py",
        "protection/setup.py",
        "catalog/access_control.py",
    ):
        guard_path = package_root / relative_path
        guard_path.parent.mkdir(parents=True, exist_ok=True)
        guard_path.write_text("# guard\n", encoding="utf-8")
    return package_root


def test_blueprint_lock_flow_uses_os_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_root = _create_guard_package_root(tmp_path=tmp_path)
    monkeypatch.setattr(authority, "resolve_bpfw_package_root", lambda: package_root)
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text("version: 1\nresponsibilities: []\n", encoding="utf-8")

    try:
        assert get_blueprint_lock_state(project_root=tmp_path) == "unlocked"
        assert lock_blueprint(project_root=tmp_path) == "locked"
        assert get_blueprint_lock_state(project_root=tmp_path) == "locked"
    finally:
        assert unlock_blueprint(project_root=tmp_path) == "unlocked"


def test_access_control_blocks_locked_blueprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_root = _create_guard_package_root(tmp_path=tmp_path)
    monkeypatch.setattr(authority, "resolve_bpfw_package_root", lambda: package_root)
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
    finally:
        unlock_blueprint(project_root=tmp_path)

    assert message == "Blueprint is locked. Run bpfw unlock before editing."


def test_resolve_protected_resources_uses_blueprint_and_guard_files(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text("version: 1\nresponsibilities: []\n", encoding="utf-8")

    resources = resolve_protected_resources(project_root=tmp_path)

    assert resources[0].path == blueprint_path
    assert resources[0].resource_type == "blueprint"
    assert [resource.resource_type for resource in resources[1:]] == ["guard", "guard", "guard", "guard"]
    assert all(resource.path.is_absolute() for resource in resources[1:])


def test_authority_status_degrades_when_a_guard_is_unlocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text("version: 1\nresponsibilities: []\n", encoding="utf-8")

    def fake_lock_state(project_root: Path, relative_path: str) -> str:
        if relative_path == "bpfw/blueprint.yaml":
            return "locked"
        return "unlocked"

    monkeypatch.setattr(authority, "get_file_lock_state", fake_lock_state)

    result = get_authority_protection_status(project_root=tmp_path)

    assert result.status == "degraded"


@pytest.mark.skipif(RUNS_AS_ROOT, reason="root can bypass POSIX write bits")
def test_locked_blueprint_rejects_direct_file_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_root = _create_guard_package_root(tmp_path=tmp_path)
    monkeypatch.setattr(authority, "resolve_bpfw_package_root", lambda: package_root)
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


def test_exact_path_os_lock_reports_missing(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.py"

    assert os_lock.lock_file(missing_path) == "missing"
    assert os_lock.unlock_file(missing_path) == "missing"
    assert os_lock.get_file_lock_state(missing_path) == "missing"
