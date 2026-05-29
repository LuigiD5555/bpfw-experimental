"""Shared runtime context for passing data between engine and integrations."""

from typing import Any

# Temporary storage for runtime context during integration execution
_integration_runtime_cache: dict[str, Any] = {}


def set_integration_runtime_cache(cache: dict[str, object]) -> None:
    """Set the runtime cache for the current integration execution.

    Args:
        cache: Runtime cache dictionary from engine context.
    """
    global _integration_runtime_cache
    _integration_runtime_cache = dict(cache)


def get_integration_runtime_cache() -> dict[str, Any]:
    """Get the runtime cache for the current integration execution.

    Returns:
        Runtime cache dictionary, or empty dict if not set.
    """
    return dict(_integration_runtime_cache)


def clear_integration_runtime_cache() -> None:
    """Clear the runtime cache after integration execution."""
    global _integration_runtime_cache
    _integration_runtime_cache = {}