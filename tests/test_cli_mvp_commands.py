import pytest

from bpfw.cli import MVP_COMMANDS, resolve_cli_command


def test_public_command_surface_is_mvp_only() -> None:
    assert MVP_COMMANDS == (
        "init",
        "inspector",
        "editor",
        "planner",
        "verify",
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
