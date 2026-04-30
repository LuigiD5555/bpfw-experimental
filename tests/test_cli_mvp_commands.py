import pytest

from bpfw.cli import MVP_COMMANDS, normalize_command


def test_public_command_surface_is_mvp_only() -> None:
    assert MVP_COMMANDS == (
        "init",
        "wizard",
        "verify",
        "lock",
        "unlock",
        "status",
        "protect",
        "repair",
    )


def test_lock_maps_without_subcommands() -> None:
    assert normalize_command("lock", None) == "lock"


def test_unlock_maps_default_and_blueprint_target() -> None:
    assert normalize_command("unlock", None) == "unlock"
    assert normalize_command("unlock", "blueprint") == "unlock"


def test_protect_maps_setup() -> None:
    assert normalize_command("protect", "setup") == "protect.setup"


def test_repair_maps_without_subcommands() -> None:
    assert normalize_command("repair", None) == "repair"


def test_catalog_commands_reject_subcommands() -> None:
    for command in ("init", "wizard", "verify", "status"):
        with pytest.raises(ValueError):
            normalize_command(command, "extra")


def test_unlock_rejects_non_blueprint_target() -> None:
    with pytest.raises(ValueError, match="unlock only supports blueprint resource"):
        normalize_command("unlock", "other")


def test_protect_rejects_missing_or_unknown_subcommand() -> None:
    with pytest.raises(ValueError, match="protect only supports setup"):
        normalize_command("protect", None)
    with pytest.raises(ValueError, match="protect only supports setup"):
        normalize_command("protect", "other")


def test_repair_rejects_subcommands() -> None:
    with pytest.raises(ValueError, match="repair does not accept subcommands"):
        normalize_command("repair", "extra")


def test_unknown_command_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown command"):
        normalize_command("unknown", None)
