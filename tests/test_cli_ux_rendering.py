from __future__ import annotations

from bpfw.cli import _print_human


def test_print_human_verify_ok_is_exact(capsys) -> None:
    payload = {
        "command_name": "verify",
        "status": "ok",
        "message": "Authority resources validated successfully",
        "primary_step": {},
        "steps": [],
    }

    _print_human(payload)
    output = capsys.readouterr().out
    assert output == "OK\n"


def test_print_human_lock_uses_message_only(capsys) -> None:
    payload = {
        "command_name": "lock",
        "status": "ok",
        "message": "Blueprint locked: bpfw/blueprint.yaml",
        "primary_step": {},
        "steps": [],
    }

    _print_human(payload)
    output = capsys.readouterr().out
    assert output == "Blueprint locked: bpfw/blueprint.yaml\n"
