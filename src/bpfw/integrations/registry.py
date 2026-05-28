"""PURPOSE registry for BPFW tools
DOMAIN  optional integrations
"""

from importlib import import_module
from inspect import signature
from pathlib import Path

from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.result import OptionalIntegrationResult


class IntegrationRegistry:
    """PURPOSE store tools by capability name
    DOMAIN  optional integrations
    """

    def __init__(self) -> None:
        """PURPOSE set up the tool registry
        DOMAIN  optional integrations
        """

        self._integrations: dict[str, OptionalIntegration] = {}
        self._load_errors: dict[str, str] = {}

    def register(self, integration: OptionalIntegration) -> None:
        """PURPOSE register an tool
        DOMAIN  optional integrations
        """

        self._integrations[integration.name] = integration

    def record_load_error(self, name: str, error_message: str) -> None:
        """PURPOSE record why an tool could not be loaded
        DOMAIN  optional integrations
        """

        self._load_errors[name] = error_message

    def list_integrations(self) -> list[OptionalIntegration]:
        """PURPOSE get registered tools
        DOMAIN  optional integrations
        """

        return list(self._integrations.values())

    def get(self, name: str) -> OptionalIntegration | None:
        """PURPOSE get one tool by name
        DOMAIN  optional integrations
        """

        return self._integrations.get(name)

    def run(
        self,
        name: str,
        project_root: Path,
        command_arguments: dict[str, str] | None = None,
    ) -> OptionalIntegrationResult:
        """PURPOSE run one tool or return a clear unavailable result
        DOMAIN  optional integrations
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
    """PURPOSE build the default tool registry
    DOMAIN  optional integrations
    """

    registry = IntegrationRegistry()
    for integration_name, module_name, class_name in (
        ("inspector", "bpfw.integrations.inspector", "InspectorIntegration"),
        ("editor", "bpfw.integrations.editor", "EditorIntegration"),
        ("planner", "bpfw.integrations.planner", "PlannerIntegration"),
        ("diff", "bpfw.integrations.diff", "DiffIntegration"),
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
