"""PURPOSE shared runtime context for passing data between engine and tools
DOMAIN  terminal UI
"""

from typing import Any

# Temporary storage for runtime context during integration execution
_integration_runtime_cache: dict[str, Any] = {}


def set_integration_runtime_cache(cache: dict[str, object]) -> None:
    """PURPOSE set the runtime cache for the tool execution
    DOMAIN  terminal UI
    """
    global _integration_runtime_cache
    _integration_runtime_cache = dict(cache)


def get_integration_runtime_cache() -> dict[str, Any]:
    """PURPOSE get the runtime cache for the tool execution
    DOMAIN  terminal UI
    """
    return dict(_integration_runtime_cache)


def clear_integration_runtime_cache() -> None:
    """PURPOSE clear the runtime cache after tool execution
    DOMAIN  terminal UI
    """
    global _integration_runtime_cache
    _integration_runtime_cache = {}