"""PURPOSE inspector view mode abstractions
DOMAIN  inspector workflow
"""

from abc import ABC, abstractmethod
from typing import List


class InspectorViewMode(ABC):
    """PURPOSE define mode-specific inspector rendering and command policy
    DOMAIN  inspector workflow
    """

    @abstractmethod
    def get_name(self) -> str:
        """PURPOSE get the stable view mode name
        DOMAIN  inspector workflow
        """

    @abstractmethod
    def get_next_mode_name(self) -> str:
        """PURPOSE get the mode name activated by the toggle command
        DOMAIN  inspector workflow
        """

    @abstractmethod
    def should_render_extended_panels(self) -> bool:
        """PURPOSE check whether extended inspector panels should be rendered
        DOMAIN  inspector workflow
        """

    @abstractmethod
    def build_command_lines(self) -> List[str]:
        """PURPOSE get the command lines displayed by this view mode
        DOMAIN  inspector workflow
        """
