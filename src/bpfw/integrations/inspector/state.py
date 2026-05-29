"""Inspector session state."""

from dataclasses import dataclass

from bpfw.integrations.inspector.view_modes import COMPACT_VIEW_MODE, FULL_VIEW_MODE
from bpfw.integrations.inspector.view_modes.base import InspectorViewMode


@dataclass
class InspectorViewState:
    """Store mutable inspector navigation and view state."""

    current_index: int
    mode_name: str
    is_running: bool = True

    @classmethod
    def from_show_all(cls, show_all: bool) -> "InspectorViewState":
        """Create initial inspector state from the terminal display flag."""

        mode_name = FULL_VIEW_MODE if show_all else COMPACT_VIEW_MODE
        return cls(current_index=0, mode_name=mode_name, is_running=True)

    def advance(self) -> None:
        """Move the inspector to the next block."""

        self.current_index += 1

    def move_back(self) -> None:
        """Move the inspector to the previous block when possible."""

        self.current_index = max(0, self.current_index - 1)

    def stop(self) -> None:
        """Mark the inspector session as stopped."""

        self.is_running = False

    def toggle_mode(self, current_view_mode: InspectorViewMode) -> None:
        """Switch to the next view mode declared by the current mode."""

        self.mode_name = current_view_mode.get_next_mode_name()
