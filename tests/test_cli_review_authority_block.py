from bpfw.cli import _print_human


def test_print_human_rv012_uses_authority_block_template(capsys) -> None:
    payload = {
        "command_name": "review",
        "status": "block",
        "message": "Workspace attempted to modify authority resource: blueprint.yaml. Direct authority edits are not allowed.",
        "primary_step": {
            "details": {
                "error_code": "RV012",
                "change_id": "change-001",
                "review_status": "BLOCK",
            },
            "affected_resources": ["/tmp/demo/blueprint.yaml"],
            "suggested_actions": ["Create a proposal or use a scoped authority command."],
        },
        "steps": [],
    }

    _print_human(payload)

    output = capsys.readouterr().out
    expected = """BPFW BLOCKED ACTION\n\nResource:\nblueprint.yaml\n\nReason:\nBlueprint is an authority resource.\n\nPolicy:\nAI or normal code changes cannot edit authority resources directly.\n\nDo not retry this edit.\n\nAllowed next action:\nCreate or accept a proposal, then request scoped authority access.\n"""
    assert output == expected
