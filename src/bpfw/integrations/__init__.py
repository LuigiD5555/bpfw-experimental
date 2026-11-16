"""Optional integrations for BPFW catalog mode."""

from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.registry import IntegrationRegistry
from bpfw.integrations.result import OptionalIntegrationResult

__all__ = [
    "IntegrationRegistry",
    "OptionalIntegration",
    "OptionalIntegrationResult",
]
