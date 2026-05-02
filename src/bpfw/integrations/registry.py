"""Registry for optional BPFW integrations."""

from importlib.metadata import EntryPoint, entry_points
from pathlib import Path

from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.result import OptionalIntegrationResult

INTEGRATION_ENTRY_POINT_GROUP = "bpfw.integrations"


class IntegrationRegistry:
    """Store optional integrations by capability name."""

    def __init__(self) -> None:
        self._integrations: dict[str, OptionalIntegration] = {}

    def register(self, integration: OptionalIntegration) -> None:
        """Register an optional integration."""

        self._integrations[integration.name] = integration

    def list_integrations(self) -> list[OptionalIntegration]:
        """Return registered optional integrations."""

        return list(self._integrations.values())

    def get(self, name: str) -> OptionalIntegration | None:
        """Return one optional integration by name."""

        return self._integrations.get(name)

    def run(self, name: str, project_root: Path) -> OptionalIntegrationResult:
        """Run one optional integration or return a clear unavailable result."""

        integration = self.get(name)
        if integration is None or not integration.is_available():
            return OptionalIntegrationResult(
                message=(
                    f"BPFW {name} integration is not available.\n\n"
                    "Next:\n"
                    "  Install or enable the integration, then run this command again."
                ),
                exit_code=1,
            )
        return integration.run(project_root=project_root)


def _load_entry_point_integration(entry_point: EntryPoint) -> OptionalIntegration | None:
    """Load one integration entry point if it implements the plugin contract."""

    try:
        integration_class = entry_point.load()
        integration = integration_class()
    except Exception:
        return None

    if not isinstance(integration, OptionalIntegration):
        return None

    return integration


def build_default_integration_registry() -> IntegrationRegistry:
    """Build the default optional integration registry from plugin entry points."""

    registry = IntegrationRegistry()
    for entry_point in entry_points(group=INTEGRATION_ENTRY_POINT_GROUP):
        integration = _load_entry_point_integration(entry_point=entry_point)
        if integration is not None:
            registry.register(integration)
    return registry
