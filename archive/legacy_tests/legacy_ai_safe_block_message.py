from bpfw.authority.ai_safe_block_message import AiSafeBlockMessage


def test_ai_safe_block_message_render_is_deterministic() -> None:
    message = AiSafeBlockMessage(
        resource="blueprint.yaml",
        reason="Blueprint is an authority resource.",
        policy="AI or normal code changes cannot edit authority resources directly.",
        allowed_next_action="Create or accept a proposal, then request scoped authority access.",
    )

    assert message.render() == (
        "BPFW BLOCKED ACTION\n\n"
        "Resource:\n"
        "blueprint.yaml\n\n"
        "Reason:\n"
        "Blueprint is an authority resource.\n\n"
        "Policy:\n"
        "AI or normal code changes cannot edit authority resources directly.\n\n"
        "Do not retry this edit.\n\n"
        "Allowed next action:\n"
        "Create or accept a proposal, then request scoped authority access."
    )
