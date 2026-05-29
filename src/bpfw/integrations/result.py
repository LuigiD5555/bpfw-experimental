"""Result objects for optional BPFW integrations."""

from dataclasses import dataclass


@dataclass
class OptionalIntegrationResult:
    """Represent the outcome of an optional integration run."""

    message: str
    exit_code: int

    @property
    def success(self) -> bool:
        """Return True when the integration completed successfully."""

        return self.exit_code == 0
