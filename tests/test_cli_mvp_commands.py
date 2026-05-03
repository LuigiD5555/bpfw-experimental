import pytest

from bpfw.cli import MVP_COMMANDS, build_parser, normalize_command


def test_public_command_surface_is_mvp_only() -> None:
    assert MVP_COMMANDS == (
        "init",
        "inspect",
        "editor",
        "verify",
        "status",
        "lock",
        "unlock",
        "repair",
    )


def test_lock_maps_without_subcommands() -> None:
    assert normalize_command("lock", None) == "lock"


def test_unlock_maps_default_and_blueprint_target() -> None:
    assert normalize_command("unlock", None) == "unlock"
    assert normalize_command("unlock", "blueprint") == "unlock"


def test_repair_maps_without_subcommands() -> None:
    assert normalize_command("repair", None) == "repair"


def test_integration_commands_map_without_subcommands() -> None:
    assert normalize_command("inspect", None) == "inspect"
    assert normalize_command("editor", None) == "editor"


def test_catalog_commands_reject_subcommands() -> None:
    for command in ("init", "inspect", "editor", "verify", "status"):
        with pytest.raises(ValueError):
            normalize_command(command, "extra")


def test_unlock_rejects_non_blueprint_target() -> None:
    with pytest.raises(ValueError, match="unlock only supports blueprint resource"):
        normalize_command("unlock", "other")


def test_repair_rejects_subcommands() -> None:
    with pytest.raises(ValueError, match="repair does not accept subcommands"):
        normalize_command("repair", "extra")


def test_external_plugin_command_maps_without_subcommands() -> None:
    assert normalize_command("external", None) == "external"


def test_external_plugin_command_rejects_subcommands() -> None:
    with pytest.raises(ValueError, match="external does not accept subcommands"):
        normalize_command("external", "extra")


def test_parser_accepts_external_plugin_command() -> None:
    parser = build_parser()

    parsed_arguments = parser.parse_args(["external"])

    assert parsed_arguments.command == "external"
