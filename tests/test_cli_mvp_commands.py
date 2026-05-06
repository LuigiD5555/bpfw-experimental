import pytest

from bpfw.cli import MVP_COMMANDS, normalize_command


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
    )


def test_lock_maps_without_subcommands() -> None:
    assert normalize_command("lock", None) == "lock"


def test_unlock_maps_default_and_blueprint_target() -> None:
    assert normalize_command("unlock", None) == "unlock"
    assert normalize_command("unlock", "blueprint") == "unlock"


def test_inspector_editor_and_planner_map_without_subcommands() -> None:
    assert normalize_command("inspector", None) == "inspector"
    assert normalize_command("editor", None) == "editor"
    assert normalize_command("planner", None) == "planner"


def test_catalog_commands_reject_subcommands() -> None:
    for command in ("init", "inspector", "editor", "planner", "verify", "status"):
        with pytest.raises(ValueError):
            normalize_command(command, "extra")


def test_unlock_rejects_non_blueprint_target() -> None:
    with pytest.raises(ValueError, match="unlock only supports blueprint resource"):
        normalize_command("unlock", "other")


def test_unknown_command_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown command"):
        normalize_command("unknown", None)