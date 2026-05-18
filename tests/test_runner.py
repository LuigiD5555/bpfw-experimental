from pathlib import Path

import pytest

from bpfw.runner import run_command_after_verify


def test_run_does_not_execute_child_command_when_verify_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def fake_verify(project_root: Path):  # noqa: ANN001
        return object(), 1

    def fake_subprocess_run(command: list[str], cwd: Path, check: bool):  # noqa: ANN001
        calls.append(command)
        raise AssertionError("subprocess should not run when verify fails")

    monkeypatch.setattr("bpfw.runner.run_verify", fake_verify)
    monkeypatch.setattr("bpfw.runner.subprocess.run", fake_subprocess_run)

    exit_code = run_command_after_verify(project_root=tmp_path, command=["python", "app.py"])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert calls == []
    assert "BPFW verify failed." in output
    assert "Execution blocked." in output


def test_run_executes_child_command_when_verify_passes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    captured_commands: list[list[str]] = []

    class CompletedProcessStub:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    def fake_verify(project_root: Path):  # noqa: ANN001
        return object(), 0

    def fake_subprocess_run(command: list[str], cwd: Path, check: bool):  # noqa: ANN001
        captured_commands.append(command)
        return CompletedProcessStub(returncode=0)

    monkeypatch.setattr("bpfw.runner.run_verify", fake_verify)
    monkeypatch.setattr("bpfw.runner.subprocess.run", fake_subprocess_run)

    exit_code = run_command_after_verify(
        project_root=tmp_path,
        command=["python", "app.py", "--debug", "--port", "8000"],
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert captured_commands == [["python", "app.py", "--debug", "--port", "8000"]]
    assert "BPFW verify passed." in output
    assert "python app.py --debug --port 8000" in output


def test_run_returns_child_process_exit_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class CompletedProcessStub:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    def fake_verify(project_root: Path):  # noqa: ANN001
        return object(), 0

    def fake_subprocess_run(command: list[str], cwd: Path, check: bool):  # noqa: ANN001
        return CompletedProcessStub(returncode=7)

    monkeypatch.setattr("bpfw.runner.run_verify", fake_verify)
    monkeypatch.setattr("bpfw.runner.subprocess.run", fake_subprocess_run)

    exit_code = run_command_after_verify(project_root=tmp_path, command=["python", "-c", "print('x')"])
    assert exit_code == 7


def test_run_handles_missing_executable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    def fake_verify(project_root: Path):  # noqa: ANN001
        return object(), 0

    def fake_subprocess_run(command: list[str], cwd: Path, check: bool):  # noqa: ANN001
        raise FileNotFoundError(command[0])

    monkeypatch.setattr("bpfw.runner.run_verify", fake_verify)
    monkeypatch.setattr("bpfw.runner.subprocess.run", fake_subprocess_run)

    exit_code = run_command_after_verify(project_root=tmp_path, command=["missing-bin"])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Executable not found: missing-bin" in output
