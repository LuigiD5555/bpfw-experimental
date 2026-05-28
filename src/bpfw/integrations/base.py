"""PURPOSE base adapter contract for BPFW tools
DOMAIN  optional integrations
"""

from abc import ABC, abstractmethod
from pathlib import Path

from bpfw.integrations.result import OptionalIntegrationResult


class OptionalIntegration(ABC):
    """PURPOSE abstract adapter for a replaceable BPFW capability
    DOMAIN  optional integrations
    """

    name: str

    @abstractmethod
    def is_available(self) -> bool:
        """PURPOSE check whether the tool can run
        DOMAIN  optional integrations
        """

    @abstractmethod
    def run(
        self,
        project_root: Path,
        command_arguments: dict[str, str] | None = None,
    ) -> OptionalIntegrationResult:
        """PURPOSE run the tool against a project root
        DOMAIN  optional integrations
        """
