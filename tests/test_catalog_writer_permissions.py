"""Tests for interactive ownership repair flow in catalog init."""

from types import SimpleNamespace

from bpfw.core.catalog import writer


def test_extract_repair_command_returns_expected_command() -> None:
    """Extract command from protection reason text."""

    reason = (
        "BPFW cannot probe lock support because path is not writable. "
        "Repair with: sudo chown -R user:user /project/bpfw && chmod -R u+rwX /project/bpfw"
    )
    command = writer._extract_repair_command(reason=reason)
    assert command == "sudo chown -R user:user /project/bpfw && chmod -R u+rwX /project/bpfw"


def test_try_interactive_permission_repair_skips_without_tty(monkeypatch) -> None:
    """Do not prompt or execute repairs in non-interactive sessions."""

    setup_result = SimpleNamespace(
        support=SimpleNamespace(
            reason="Repair with: sudo chown -R user:user /project/bpfw && chmod -R u+rwX /project/bpfw"
        )
    )
    monkeypatch.setattr(writer.sys.stdin, "isatty", lambda: False)

    assert writer._try_interactive_permission_repair(setup_result=setup_result) is False


def test_try_interactive_permission_repair_runs_in_tty_without_prompt(monkeypatch) -> None:
    """Run repair command automatically when terminal is interactive."""

    setup_result = SimpleNamespace(
        support=SimpleNamespace(
            reason="Repair with: sudo chown -R user:user /project/bpfw && chmod -R u+rwX /project/bpfw"
        )
    )
    executed_command: dict[str, str] = {}

    monkeypatch.setattr(writer.sys.stdin, "isatty", lambda: True)

    def fake_run(command: str, shell: bool, check: bool):  # noqa: ANN001
        executed_command["value"] = command
        assert shell is True
        assert check is False
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(writer.subprocess, "run", fake_run)

    assert writer._try_interactive_permission_repair(setup_result=setup_result) is True
    assert executed_command["value"].startswith("sudo chown -R user:user")
