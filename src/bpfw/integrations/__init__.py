"""Dormant integrations seam for BPFW MVP Catalog Mode."""

from bpfw.integrations.base import ExternalToolAdapter
from bpfw.integrations.registry import IntegrationRegistry
from bpfw.integrations.result import ExternalToolFinding

__all__ = [
    "ExternalToolAdapter",
    "ExternalToolFinding",
    "IntegrationRegistry",
]
