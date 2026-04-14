"""Explicit registry error types for catalog validation enforcement."""


class UnregisteredComponentError(Exception):
    """Raised when a component is not declared in the catalog."""


class ForbiddenImplementationError(Exception):
    """Raised when an implementation is not listed as allowed in the catalog."""


class DuplicateActiveImplementationError(Exception):
    """Raised when a second implementation is activated for an already-active component."""


class InactiveLifecycleError(Exception):
    """Raised when activation is attempted for a responsibility whose lifecycle_state is not 'active'."""
