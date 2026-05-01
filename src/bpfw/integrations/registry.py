"""Registry for optional BPFW integrations."""

from importlib import import_module
from pathlib import Path

from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.result import OptionalIntegrationResult


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


def build_default_integration_registry() -> IntegrationRegistry:
    """Build the default optional integration registry."""

    registry = IntegrationRegistry()
    for module_name, class_name in (
        ("bpfw.integrations.wizard", "RichWizardIntegration"),
        ("bpfw.integrations.repair", "ProtectionRepairIntegration"),
    ):
        try:
            module = import_module(module_name)
            integration_class = getattr(module, class_name)
        except (ImportError, AttributeError):
            continue
        registry.register(integration_class())
    return registry
