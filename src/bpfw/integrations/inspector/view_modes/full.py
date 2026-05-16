"""Full inspector view mode."""

from typing import List

from bpfw.integrations.inspector.commands import CUSTOM_DOMAIN_KEY, DOMAIN_SUGGESTION_KEYS
from bpfw.integrations.inspector.view_modes.base import InspectorViewMode
from bpfw.integrations.shared.cli_runtime import quit_command_label
from bpfw.integrations.shared.visual_theme import COMMAND_SEPARATOR
from bpfw.integrations.shared.visual_width import pad_text

COMMAND_COLUMN_WIDTHS = (28, 22)


class FullInspectorViewMode(InspectorViewMode):
    """Define full inspector rendering and command policy."""

    def get_name(self) -> str:
        """Return the stable view mode name."""

        return "full"

    def get_next_mode_name(self) -> str:
        """Return the mode name activated by the toggle command."""

        return "compact"

    def should_render_extended_panels(self) -> bool:
        """Return true because full mode renders extended panels."""

        return True

    def build_command_lines(self) -> List[str]:
        """Return the full command lines."""

        return [
            _format_command_row("[1-5] purpose suggestion", "[6] custom purpose"),
            _format_command_row(f"[{'|'.join(DOMAIN_SUGGESTION_KEYS)}] domain", f"[{CUSTOM_DOMAIN_KEY}] custom domain"),
            _format_command_row("[z|x|c|v] status", "[n] name", "[i] interface"),
            _format_command_row("[o] notes", "[h] help", quit_command_label()),
            _format_command_row("[Enter] save + next", "[b] back", "[a] compact view"),
            COMMAND_SEPARATOR,
            "Note: press ctrl+c to quit. Type a command key and press Enter, for example 1 + Enter.",
        ]


def _format_command_row(*commands: str) -> str:
    """Format command labels into stable visual columns."""

    if not commands:
        return ""
    formatted_parts: list[str] = []
    for command, column_width in zip(commands[:-1], COMMAND_COLUMN_WIDTHS):
        formatted_parts.append(pad_text(command, column_width))
    formatted_parts.append(commands[-1])
    return "".join(formatted_parts)
