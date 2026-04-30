"""Registry for dormant external tool integrations."""

from pathlib import Path

from bpfw.integrations.base import ExternalToolAdapter
from bpfw.integrations.result import ExternalToolFinding


class IntegrationRegistry:
    """Store and run available external tool adapters."""

    def __init__(self) -> None:
        self._adapters: list[ExternalToolAdapter] = []

    def register(self, adapter: ExternalToolAdapter) -> None:
        """Register an external tool adapter."""

        self._adapters.append(adapter)

    def list_adapters(self) -> list[ExternalToolAdapter]:
        """Return registered adapters without exposing mutable state."""

        return list(self._adapters)

    def run_available(self, project_root: Path) -> list[ExternalToolFinding]:
        """Run all currently available adapters."""

        findings: list[ExternalToolFinding] = []
        for adapter in self._adapters:
            if adapter.is_available():
                findings.extend(adapter.run(project_root=project_root))
        return findings
