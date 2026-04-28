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


def test_print_human_discover_uses_message_only(capsys) -> None:
    payload = {
        "command_name": "discover",
        "status": "info",
        "message": (
            "Discovered undeclared file:\n"
            "src/application/query/retry_policy.py\n\n"
            "Suggested responsibility:\n"
            "query_execution\n\n"
            "Proposal created:\n"
            "proposal-retry-policy"
        ),
        "primary_step": {},
        "steps": [],
    }

    _print_human(payload)
    output = capsys.readouterr().out
    assert output == (
        "Discovered undeclared file:\n"
        "src/application/query/retry_policy.py\n\n"
        "Suggested responsibility:\n"
        "query_execution\n\n"
        "Proposal created:\n"
        "proposal-retry-policy\n"
    )

