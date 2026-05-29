"""Inspector view mode abstractions."""

from abc import ABC, abstractmethod
from typing import List


class InspectorViewMode(ABC):
    """Define mode-specific inspector rendering and command policy."""

    @abstractmethod
    def get_name(self) -> str:
        """Return the stable view mode name."""

    @abstractmethod
    def get_next_mode_name(self) -> str:
        """Return the mode name activated by the toggle command."""

    @abstractmethod
    def should_render_extended_panels(self) -> bool:
        """Return whether extended inspector panels should be rendered."""

    @abstractmethod
    def build_command_lines(self) -> List[str]:
        """Return the command lines displayed by this view mode."""
