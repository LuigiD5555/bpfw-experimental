"""Registry for dormant external tool integrations."""

from pathlib import Path
from typing import List

from bpfw.integrations.base import ExternalToolAdapter
from bpfw.integrations.result import ExternalToolFinding


class IntegrationRegistry:
    """Store and run available external tool adapters."""

    def __init__(self) -> None:
        self._adapters: List[ExternalToolAdapter] = []

    def register(self, adapter: ExternalToolAdapter) -> None:
        """Register an external tool adapter."""
        self._adapters.append(adapter)

    def list_adapters(self) -> List[ExternalToolAdapter]:
        """Return a copy of registered adapters."""
        return list(self._adapters)

    def run_available(self, project_root: Path) -> List[ExternalToolFinding]:
        """Run all currently available adapters.

        Skips adapters that report as unavailable.
        Does not convert failures into verify findings.
        """
        findings: List[ExternalToolFinding] = []
        for adapter in self._adapters:
            if adapter.is_available():
                findings.extend(adapter.run(project_root=project_root))
        return findings
