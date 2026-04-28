from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AiSafeBlockMessage:
    """Builds deterministic block messages that discourage repeated invalid edits."""

    resource: str
    reason: str
    policy: str
    allowed_next_action: str

    def render(self) -> str:
        """Render a block message optimized for AI-assisted workflows."""

        return (
            "BPFW BLOCKED ACTION\n\n"
            "Resource:\n"
            f"{self.resource}\n\n"
            "Reason:\n"
            f"{self.reason}\n\n"
            "Policy:\n"
            f"{self.policy}\n\n"
            "Do not retry this edit.\n\n"
            "Allowed next action:\n"
            f"{self.allowed_next_action}"
        )
