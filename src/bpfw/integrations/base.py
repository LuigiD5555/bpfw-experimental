"""Base adapter contract for optional BPFW integrations."""

from abc import ABC, abstractmethod
from pathlib import Path

from bpfw.integrations.result import OptionalIntegrationResult


class OptionalIntegration(ABC):
    """Abstract adapter for a replaceable BPFW capability."""

    name: str

    @abstractmethod
    def is_available(self) -> bool:
        """Return True when the optional integration can run."""

    @abstractmethod
    def run(
        self,
        project_root: Path,
        command_arguments: dict[str, str] | None = None,
    ) -> OptionalIntegrationResult:
        """Run the optional integration against a project root."""
