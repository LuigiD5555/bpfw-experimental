import pytest
from pathlib import Path
import sys

from bpfw.cli import (
    MVP_COMMANDS,
    main,
    resolve_cli_command,
    _migrate_root_blocks_to_default_shard,
    _attempt_permission_repair,
)


def test_public_command_surface_is_mvp_only() -> None:
    assert MVP_COMMANDS == (
        "init",
        "inspector",
        "editor",
        "planner",
        "verify",
        "run",
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
    for command in ("init", "inspector", "editor", "planner", "verify", "status"):
        with pytest.raises(ValueError):
            resolve_cli_command(command, "extra")


def test_unlock_rejects_non_blueprint_target() -> None:
    with pytest.raises(ValueError, match="unlock only supports blueprint resource"):
        resolve_cli_command("unlock", "other")


def test_unknown_command_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown command"):
        resolve_cli_command("unknown", None)


def test_resolve_cli_command_is_case_and_whitespace_insensitive() -> None:
    assert resolve_cli_command("  VERIFY  ", None) == "verify"
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


def test_migrate_root_blocks_to_default_shard_moves_legacy_blocks(tmp_path: Path) -> None:
    import yaml

    (tmp_path / "bpfw" / "blocks").mkdir(parents=True)
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    core_shard_path = tmp_path / "bpfw" / "blocks" / "core.yaml"

    blueprint_data = {
        "version": 1,
        "project": {"id": "demo", "name": "demo"},
        "authority": {"layout": "sharded", "default_shard": "bpfw/blocks/core.yaml"},
        "includes": ["bpfw/blocks/core.yaml"],
        "blocks": [{"id": "legacy_1"}, {"id": "legacy_2"}],
    }
    core_data = {"blocks": [{"id": "legacy_2"}, {"id": "existing_1"}]}

    blueprint_path.write_text(yaml.safe_dump(blueprint_data, sort_keys=False), encoding="utf-8")
    core_shard_path.write_text(yaml.safe_dump(core_data, sort_keys=False), encoding="utf-8")

    summary = _migrate_root_blocks_to_default_shard(project_root=tmp_path)
    migrated_blueprint = yaml.safe_load(blueprint_path.read_text(encoding="utf-8"))
    migrated_core = yaml.safe_load(core_shard_path.read_text(encoding="utf-8"))

    assert summary["migrated"] == 1
    assert summary["skipped"] == 1
    assert "blocks" not in migrated_blueprint
    assert migrated_blueprint["includes"] == ["bpfw/blocks/core.yaml"]
    assert {block["id"] for block in migrated_core["blocks"]} == {"legacy_1", "legacy_2", "existing_1"}


def test_attempt_permission_repair_executes_sudo_sequence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "bpfw" / "blocks").mkdir(parents=True)
    calls: list[list[str]] = []

    class _Completed:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    def fake_run(command: list[str], cwd: Path, check: bool):  # noqa: ANN001
        calls.append(command)
        return _Completed(0)

    monkeypatch.setattr("bpfw.cli.subprocess.run", fake_run)
    error = PermissionError(13, "Permission denied", str(tmp_path / "bpfw" / "blueprint.yaml"))

    assert _attempt_permission_repair(project_root=tmp_path, error=error) is True
    assert calls[0] == ["sudo", "-v"]
    assert calls[1][0:2] == ["sudo", "chown"]
    assert calls[2][0:2] == ["sudo", "chmod"]


def test_migrate_root_blocks_to_default_shard_skips_duplicate_code_declarations(tmp_path: Path) -> None:
    import yaml

    (tmp_path / "bpfw" / "blocks").mkdir(parents=True)
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    core_shard_path = tmp_path / "bpfw" / "blocks" / "core.yaml"

    blueprint_data = {
        "version": 1,
        "project": {"id": "demo", "name": "demo"},
        "authority": {"layout": "sharded", "default_shard": "bpfw/blocks/core.yaml"},
        "includes": ["bpfw/blocks/core.yaml"],
        "blocks": [
            {
                "id": "legacy_duplicate",
                "code": {
                    "path": "src/bpfw/authority/document.py",
                    "symbol": "AuthorityDocument.get_blocks",
                    "kind": "method",
                },
            }
        ],
    }
    core_data = {
        "blocks": [
            {
                "id": "existing_reference",
                "code": {
                    "path": "src/bpfw/authority/document.py",
                    "symbol": "AuthorityDocument.get_blocks",
                    "kind": "method",
                },
            }
        ]
    }

    blueprint_path.write_text(yaml.safe_dump(blueprint_data, sort_keys=False), encoding="utf-8")
    core_shard_path.write_text(yaml.safe_dump(core_data, sort_keys=False), encoding="utf-8")

    summary = _migrate_root_blocks_to_default_shard(project_root=tmp_path)
    migrated_core = yaml.safe_load(core_shard_path.read_text(encoding="utf-8"))

    assert summary["migrated"] == 0
    assert summary["skipped"] == 1
    assert len(migrated_core["blocks"]) == 1


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
