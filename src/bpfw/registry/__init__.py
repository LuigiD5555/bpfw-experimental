"""Registry contracts for framework-level gatekeeping."""

from bpfw.registry.errors import (
    DuplicateActiveImplementationError,
    ForbiddenImplementationError,
    InactiveLifecycleError,
    UnregisteredComponentError,
)
from bpfw.registry.gatekeeper import (
    assert_single_active_implementation,
    build_registry_snapshot,
    clear_registry_state,
    register_component,
    reject_component,
    validate_component_registration,
    validate_implementation_registration,
)

__all__ = [
    "DuplicateActiveImplementationError",
    "ForbiddenImplementationError",
    "InactiveLifecycleError",
    "UnregisteredComponentError",
    "assert_single_active_implementation",
    "build_registry_snapshot",
    "clear_registry_state",
    "register_component",
    "reject_component",
    "validate_component_registration",
    "validate_implementation_registration",
]
