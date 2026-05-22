import pytest
from pathlib import Path
import sys

from bpfw.cli import (
    MVP_COMMANDS,
    main,
    resolve_cli_command,
)


def test_public_command_surface_is_mvp_only() -> None:
    assert MVP_COMMANDS == (
        "init",
        "inspector",
        "editor",
        "planner",
        "verify",
        "run",
        "watch",
        "lock",
        "unlock",
        "status",
        "reshard",
    )


def test_lock_maps_without_subcommands() -> None:
    assert resolve_cli_command("lock", None) == "lock"


def test_unlock_maps_default_and_blueprint_target() -> None:
    assert resolve_cli_command("unlock", None) == "unlock"
    assert resolve_cli_command("unlock", "blueprint") == "unlock"


def test_inspector_editor_and_planner_map_without_subcommands() -> None:
    assert resolve_cli_command("inspector", None) == "inspector"
    assert resolve_cli_command("editor", None) == "editor"
    assert resolve_cli_command("planner", None) == "planner"


def test_catalog_commands_reject_subcommands() -> None:
    for command in ("init", "inspector", "editor", "planner", "watch", "status"):
        with pytest.raises(ValueError):
            resolve_cli_command(command, "extra")


def test_verify_accepts_supported_filters() -> None:
    assert resolve_cli_command("verify", "undeclared") == "verify"
    assert resolve_cli_command("verify", "missing") == "verify"
    assert resolve_cli_command("verify", "duplicate") == "verify"
    assert resolve_cli_command("verify", "secret") == "verify"
    assert resolve_cli_command("verify", "invalid") == "verify"
    assert resolve_cli_command("verify", "all") == "verify"


def test_verify_rejects_unknown_filter() -> None:
    with pytest.raises(ValueError, match="unknown verify filter"):
        resolve_cli_command("verify", "extra")


def test_unlock_rejects_non_blueprint_target() -> None:
    with pytest.raises(ValueError, match="unlock only supports blueprint resource"):
        resolve_cli_command("unlock", "other")


def test_unknown_command_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown command"):
        resolve_cli_command("unknown", None)


def test_resolve_cli_command_is_case_and_whitespace_insensitive() -> None:
    assert resolve_cli_command("  VERIFY  ", None) == "verify"
    assert resolve_cli_command("  WATCH  ", None) == "watch"
    assert resolve_cli_command(" unlock ", "  BLUEPRINT  ") == "unlock"


def test_main_help_uses_curated_bpfw_format() -> None:
    """Ensure top-level CLI help renders the curated command overview."""

    from bpfw.cli import MAIN_HELP_TEXT, build_parser

    assert build_parser().format_help() == f"{MAIN_HELP_TEXT}\n"


def test_main_help_hides_internal_and_inspector_specific_options() -> None:
    """Ensure top-level CLI help hides non-global implementation options."""

    from bpfw.cli import build_parser

    rendered_help = build_parser().format_help()

    assert "--ttl" not in rendered_help
    assert "--accept-scan" not in rendered_help
    assert "--force-new" not in rendered_help
    assert "-a, --all" not in rendered_help
    assert "bpfw inspector --all" in rendered_help


def test_reshard_is_blocked_as_public_command(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Reshard must print a blocking message and return non-zero."""
    monkeypatch.setattr(
        sys, "argv", ["bpfw", "reshard", "--project-root", str(tmp_path)]
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code != 0
    assert "no longer a public workflow" in output


def test_run_requires_command_and_prints_usage(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["bpfw", "run"])

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code != 0
    assert "Missing command." in output
    assert "Usage:" in output
    assert "bpfw run -- <command>" in output


def test_run_passes_command_arguments_after_dash_dash(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured_command: list[str] = []

    def fake_run_command_after_verify(project_root: Path, command: list[str]) -> int:
        captured_command.extend(command)
        return 0

    monkeypatch.setattr(
        "bpfw.cli.run_command_after_verify",
        fake_run_command_after_verify,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bpfw",
            "run",
            "--project-root",
            str(tmp_path),
            "--",
            "python",
            "app.py",
            "--debug",
            "--port",
            "8000",
        ],
    )

    exit_code = main()

    assert exit_code == 0
    assert captured_command == ["python", "app.py", "--debug", "--port", "8000"]
