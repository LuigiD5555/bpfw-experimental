"""PURPOSE compact inspector view mode
DOMAIN  inspector workflow
"""

from typing import List

from bpfw.integrations.inspector.view_modes.base import InspectorViewMode
from bpfw.integrations.shared.visual_theme import COMMAND_SEPARATOR
from bpfw.integrations.shared.visual_width import pad_text

COMMAND_COLUMN_WIDTHS = (28, 22)


class CompactInspectorViewMode(InspectorViewMode):
    """PURPOSE define compact inspector rendering and command policy
    DOMAIN  inspector workflow
    """

    def get_name(self) -> str:
        """PURPOSE get the stable view mode name
        DOMAIN  inspector workflow
        """

        return "compact"

    def get_next_mode_name(self) -> str:
        """PURPOSE get the mode name activated by the toggle command
        DOMAIN  inspector workflow
        """

        return "full"

    def should_render_extended_panels(self) -> bool:
        """PURPOSE get false because compact mode hides extended panels
        DOMAIN  inspector workflow
        """

        return False

    def build_command_lines(self) -> List[str]:
        """PURPOSE get the compact command lines
        DOMAIN  inspector workflow
        """

        return [
            _format_command_row("[h] help", "[q] quit"),
            _format_command_row("[Enter] save + next", "[b] back", "[a] full view"),
            COMMAND_SEPARATOR,
            "Note: q/Q or ctrl+c quits. Type a command key and press Enter, for example p1 + Enter.",
        ]


def _format_command_row(*commands: str) -> str:
    """PURPOSE format command labels into stable visual columns
    DOMAIN  inspector workflow
    """

    if not commands:
        return ""
    formatted_parts: list[str] = []
    for command, column_width in zip(commands[:-1], COMMAND_COLUMN_WIDTHS):
        formatted_parts.append(pad_text(command, column_width))
    formatted_parts.append(commands[-1])
    return "".join(formatted_parts)
