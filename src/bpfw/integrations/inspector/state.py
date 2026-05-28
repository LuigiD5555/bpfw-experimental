"""PURPOSE inspector session state
DOMAIN  inspector workflow
"""

from dataclasses import dataclass

from bpfw.integrations.inspector.view_modes import COMPACT_VIEW_MODE, FULL_VIEW_MODE
from bpfw.integrations.inspector.view_modes.base import InspectorViewMode


@dataclass
class InspectorViewState:
    """PURPOSE store mutable inspector navigation and view state
    DOMAIN  inspector workflow
    """

    current_index: int
    mode_name: str
    is_running: bool = True

    @classmethod
    def from_show_all(cls, show_all: bool) -> "InspectorViewState":
        """PURPOSE create initial inspector state from the terminal command display flag
        DOMAIN  inspector workflow
        """

        mode_name = FULL_VIEW_MODE if show_all else COMPACT_VIEW_MODE
        return cls(current_index=0, mode_name=mode_name, is_running=True)

    def advance(self) -> None:
        """PURPOSE move the inspector to the next block
        DOMAIN  inspector workflow
        """

        self.current_index += 1

    def move_back(self) -> None:
        """PURPOSE move the inspector to the previous block when possible
        DOMAIN  inspector workflow
        """

        self.current_index = max(0, self.current_index - 1)

    def stop(self) -> None:
        """PURPOSE mark the inspector session as stopped
        DOMAIN  inspector workflow
        """

        self.is_running = False

    def toggle_mode(self, current_view_mode: InspectorViewMode) -> None:
        """PURPOSE switch to the next view mode declared by the mode
        DOMAIN  inspector workflow
        """

        self.mode_name = current_view_mode.get_next_mode_name()
