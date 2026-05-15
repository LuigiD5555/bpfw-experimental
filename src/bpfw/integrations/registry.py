"""Registry for optional BPFW integrations."""

from importlib import import_module
from inspect import signature
from pathlib import Path

from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.result import OptionalIntegrationResult


class IntegrationRegistry:
    """Store optional integrations by capability name."""

    def __init__(self) -> None:
        """Initialize the integration registry."""

        self._integrations: dict[str, OptionalIntegration] = {}
        self._load_errors: dict[str, str] = {}

    def register(self, integration: OptionalIntegration) -> None:
        """Register an optional integration.

        Args:
            integration: Integration instance to register by name.
        """

        self._integrations[integration.name] = integration

    def record_load_error(self, name: str, error_message: str) -> None:
        """Record why an integration could not be loaded.

        Args:
            name: Integration name requested by the command registry.
            error_message: Human-readable loading failure.
        """

        self._load_errors[name] = error_message

    def list_integrations(self) -> list[OptionalIntegration]:
        """Return registered optional integrations.

        Returns:
            Registered optional integration instances.
        """

        return list(self._integrations.values())

    def get(self, name: str) -> OptionalIntegration | None:
        """Return one optional integration by name.

        Args:
            name: Integration name to retrieve.

        Returns:
            The matching integration, or None when unavailable.
        """

        return self._integrations.get(name)

    def run(
        self,
        name: str,
        project_root: Path,
        command_arguments: dict[str, str] | None = None,
    ) -> OptionalIntegrationResult:
        """Run one optional integration or return a clear unavailable result.

        Args:
            name: Integration name to run.
            project_root: Project root where the integration should run.
            command_arguments: Runtime options forwarded from the CLI command.

        Returns:
            Integration result with the integration output or a clear loading error.
        """

        integration = self.get(name)
        if integration is None:
            details = self._load_errors.get(name)
            extra = f"\n\nLoad error:\n  {details}" if details else ""
            return OptionalIntegrationResult(
                message=(
                    f"BPFW {name} integration is not available.{extra}\n\n"
                    "Next:\n"
                    "  Reinstall the current package, then run this command again.\n"
                    "  If the problem continues, run:\n"
                    "    python -c \"from bpfw.integrations.registry import build_default_integration_registry; "
                    "print([i.name for i in build_default_integration_registry().list_integrations()])\""
                ),
                exit_code=1,
            )

        if not integration.is_available():
            return OptionalIntegrationResult(
                message=(
                    f"BPFW {name} integration is disabled.\n\n"
                    "Next:\n"
                    "  Enable the integration, then run this command again."
                ),
                exit_code=1,
            )

        run_signature = signature(integration.run)
        if "command_arguments" not in run_signature.parameters:
            return integration.run(project_root=project_root)
        return integration.run(
            project_root=project_root,
            command_arguments=command_arguments or {},
        )


def build_default_integration_registry() -> IntegrationRegistry:
    """Build the default optional integration registry.

    Returns:
        Registry containing all integrations that can be imported successfully.
    """

    registry = IntegrationRegistry()
    for integration_name, module_name, class_name in (
        ("inspector", "bpfw.integrations.inspector", "InspectorIntegration"),
        ("editor", "bpfw.integrations.editor", "EditorIntegration"),
        ("planner", "bpfw.integrations.planner", "PlannerIntegration"),
    ):
        try:
            module = import_module(module_name)
            integration_class = getattr(module, class_name)
        except ImportError as import_error:
            registry.record_load_error(
                name=integration_name,
                error_message=f"Could not import {module_name}: {import_error}",
            )
            continue
        except AttributeError as attribute_error:
            registry.record_load_error(
                name=integration_name,
                error_message=f"{module_name} does not expose {class_name}: {attribute_error}",
            )
            continue
        registry.register(integration_class())
    return registry
