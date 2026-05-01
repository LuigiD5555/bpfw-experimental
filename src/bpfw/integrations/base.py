"""Base adapter contract for dormant external tool integrations."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from bpfw.integrations.result import ExternalToolFinding


class ExternalToolAdapter(ABC):
    """Abstract adapter for future external analysis tools."""

    name: str

    @abstractmethod
    def is_available(self) -> bool:
        """Return True when the external tool is available."""

    @abstractmethod
    def run(self, project_root: Path) -> List[ExternalToolFinding]:
        """Run the external tool against a project root."""
