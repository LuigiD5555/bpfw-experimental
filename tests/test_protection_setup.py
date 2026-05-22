"""Tests for protection setup preflight behavior."""

from pathlib import Path

from bpfw.core.protection.capabilities import LockSupportResult
from bpfw.core.protection import capabilities
from bpfw.core.protection import setup


def test_run_protection_setup_stops_before_locking_when_support_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify unsupported filesystems stop setup before real authority files are mutated."""

    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text("version: 1\n", encoding="utf-8")
    support = LockSupportResult(
        supported=False,
        status="unsupported",
        reason="Immutable flags are unavailable.",
        checked_path=tmp_path / "bpfw" / ".lock_support_check",
    )
    lock_called = False

    def fake_check_lock_support(project_root: Path) -> LockSupportResult:
        """Return an unsupported capability result for the test project."""

        assert project_root == tmp_path
        return support

    def fake_lock_authority(project_root: Path):  # noqa: ANN202
        """Fail the test if real authority locking is attempted."""

        nonlocal lock_called
        lock_called = True
        raise AssertionError("lock_authority must not run after failed preflight")

    monkeypatch.setattr(setup, "check_lock_support", fake_check_lock_support)
    monkeypatch.setattr(setup, "lock_authority", fake_lock_authority)

    result = setup.run_protection_setup(project_root=tmp_path)

    assert result.allowed is False
    assert result.lock_state == "unsupported"
    assert result.support == support
    assert lock_called is False


def test_run_protection_setup_allows_explicit_unprotected_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify --allow-unprotected makes init succeed without pretending OS lock worked."""

    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text("version: 1\n", encoding="utf-8")
    support = LockSupportResult(
        supported=False,
        status="unsupported",
        reason="Immutable flags are unavailable.",
        checked_path=tmp_path / "bpfw" / ".lock_support_check",
    )

    def fake_check_lock_support(project_root: Path) -> LockSupportResult:
        """Return an unsupported capability result for the test project."""

        assert project_root == tmp_path
        return support

    monkeypatch.setattr(setup, "check_lock_support", fake_check_lock_support)

    result = setup.run_protection_setup(
        project_root=tmp_path,
        allow_unprotected=True,
    )
    message = setup.format_setup_summary(result=result)

    assert result.allowed is True
    assert result.lock_state == setup.UNPROTECTED_STATUS
    assert "BPFW protection disabled." in message
    assert "disabled by --allow-unprotected" in message
    assert "protection configured" not in message


def test_run_protection_setup_allows_degraded_protection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify degraded protection is allowed without using unprotected mode."""

    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text("version: 1\n", encoding="utf-8")
    support = LockSupportResult(
        supported=True,
        status="degraded",
        reason="Read-only protection was enabled for local development.",
        checked_path=tmp_path / "bpfw" / ".lock_support_check",
        backend="readonly_weak",
    )

    monkeypatch.setattr(setup, "check_lock_support", lambda project_root: support)
    monkeypatch.setattr(setup, "lock_authority", lambda project_root: type("Result", (), {"status": "degraded"})())

    result = setup.run_protection_setup(project_root=tmp_path)
    message = setup.format_setup_summary(result=result)

    assert result.allowed is True
    assert result.lock_state == "degraded"
    assert "BPFW protection partially configured." in message
    assert "os lock: partially enabled" in message
    assert "backend: readonly_weak" in message


def test_format_setup_summary_never_claims_unsupported_is_configured(
    tmp_path: Path,
) -> None:
    """Verify unsupported setup results are rendered as failures."""

    result = setup.ProtectionSetupResult(
        blueprint_exists=True,
        lock_state="unsupported",
        support=LockSupportResult(
            supported=False,
            status="unsupported",
            reason="Immutable flags are unavailable.",
            checked_path=tmp_path / "bpfw" / ".lock_support_check",
        ),
    )

    message = setup.format_setup_summary(result=result)

    assert "BPFW protection failed." in message
    assert "os lock: unsupported" in message
    assert "BPFW protection configured." not in message
    assert "Immutable flags are unavailable." in message


def test_format_setup_summary_prioritizes_filesystem_fix_for_weak_mount(
    tmp_path: Path,
) -> None:
    """Verify weak-mount failures recommend moving or remounting before sudo."""

    result = setup.ProtectionSetupResult(
        blueprint_exists=True,
        lock_state="unsupported",
        support=LockSupportResult(
            supported=False,
            status="unsupported",
            reason=(
                "The project path is on a fuseblk filesystem mounted at /mnt/Documents. "
                "This mount does not support strong POSIX authority protection, and read-only "
                "permission protection did not block normal writes."
            ),
            checked_path=tmp_path / "bpfw" / ".lock_support_check",
        ),
    )

    message = setup.format_setup_summary(result=result)

    assert "Move the project to a filesystem that enforces POSIX ownership or permissions" in message
    assert "remount this filesystem with real permission support" in message
    assert "Run this command from an interactive terminal where sudo can prompt" not in message


def test_posix_support_reports_unsupported_when_readonly_weak_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify weak filesystems are unsupported only when read-only writes still work."""

    immutable_enable_called = False
    ownership_called = False

    def fake_find_mount_context(path: Path) -> capabilities.MountContext:
        """Return a non-POSIX mount context for the project path."""

        return capabilities.MountContext(
            mount_point=tmp_path,
            filesystem_type="fuseblk",
        )

    def fake_run_immutable_command(platform_name: str, path: Path, enable: bool) -> bool:
        """Record whether the capability check tried to enable immutable flags."""

        nonlocal immutable_enable_called
        if enable:
            immutable_enable_called = True
        return False

    def fake_can_toggle_root_ownership(check_path: Path, check_directory: Path) -> bool:
        """Record whether the capability check tried root ownership."""

        nonlocal ownership_called
        ownership_called = True
        return False

    monkeypatch.setattr(capabilities, "_find_mount_context", fake_find_mount_context)
    monkeypatch.setattr(capabilities, "_run_immutable_command", fake_run_immutable_command)
    monkeypatch.setattr(capabilities, "_can_toggle_root_ownership", fake_can_toggle_root_ownership)
    monkeypatch.setattr(capabilities, "_can_apply_readonly_weak_lock", lambda **kwargs: False)

    result = capabilities._check_posix_lock_support(
        project_root=tmp_path,
        platform_name="linux",
    )

    assert result.supported is False
    assert result.status == "unsupported"
    assert result.backend == "unsupported"
    assert "fuseblk filesystem" in result.reason
    assert "read-only permission protection did not block normal writes" in result.reason
    assert immutable_enable_called is False
    assert ownership_called is False


def test_posix_support_degrades_when_readonly_weak_blocks_writes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify weak filesystems can use read-only protection when it blocks writes."""

    monkeypatch.setattr(
        capabilities,
        "_find_mount_context",
        lambda path: capabilities.MountContext(
            mount_point=tmp_path,
            filesystem_type="fuseblk",
        ),
    )
    monkeypatch.setattr(capabilities, "_run_immutable_command", lambda **kwargs: False)
    monkeypatch.setattr(capabilities, "_can_toggle_root_ownership", lambda **kwargs: False)
    monkeypatch.setattr(capabilities, "_can_apply_readonly_weak_lock", lambda **kwargs: True)

    result = capabilities._check_posix_lock_support(
        project_root=tmp_path,
        platform_name="linux",
    )

    assert result.supported is True
    assert result.status == "degraded"
    assert result.backend == "readonly_weak"
    assert "read-only protection was enabled for local development" in result.reason


def test_ntfs3_support_is_checked_by_real_capabilities(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify kernel ntfs3 mounts are tested instead of rejected by name."""

    immutable_enable_called = False

    def fake_find_mount_context(path: Path) -> capabilities.MountContext:
        """Return a kernel ntfs3 mount context for the project path."""

        return capabilities.MountContext(
            mount_point=tmp_path,
            filesystem_type="ntfs3",
        )

    def fake_run_immutable_command(platform_name: str, path: Path, enable: bool) -> bool:
        """Record whether the capability check tried immutable flags."""

        nonlocal immutable_enable_called
        if enable:
            immutable_enable_called = True
        return False

    monkeypatch.setattr(capabilities, "_find_mount_context", fake_find_mount_context)
    monkeypatch.setattr(capabilities, "_run_immutable_command", fake_run_immutable_command)
    monkeypatch.setattr(capabilities, "_can_toggle_root_ownership", lambda **kwargs: False)
    monkeypatch.setattr(capabilities, "_can_apply_readonly_weak_lock", lambda **kwargs: False)

    result = capabilities._check_posix_lock_support(
        project_root=tmp_path,
        platform_name="linux",
    )

    assert result.status == "unsupported"
    assert "read-only permission protection did not block normal writes" in result.reason
    assert immutable_enable_called is True


def test_not_writable_reason_includes_owner_repair_command(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify non-writable probe reason includes a concrete ownership repair command."""

    check_directory = tmp_path / "bpfw" / ".lock_support_check_dir"
    check_directory.parent.mkdir(parents=True)
    current_owner_uid = check_directory.parent.stat().st_uid
    monkeypatch.setattr(capabilities.os, "geteuid", lambda: current_owner_uid + 1)

    reason = capabilities._format_not_writable_reason(check_directory=check_directory)

    assert "project path is not writable" in reason
    assert "Repair with: sudo chown -R " in reason
    assert str(check_directory.parent) in reason
    assert "chmod -R u+rwX" in reason
