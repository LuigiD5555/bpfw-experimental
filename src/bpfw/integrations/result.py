"""PURPOSE result objects for BPFW tools
DOMAIN  optional integrations
"""

from dataclasses import dataclass


@dataclass
class OptionalIntegrationResult:
    """PURPOSE store information about the outcome of an tool run
    DOMAIN  optional integrations
    """

    message: str
    exit_code: int

    @property
    def success(self) -> bool:
        """PURPOSE check whether the tool completed successfully
        DOMAIN  optional integrations
        """

        return self.exit_code == 0
