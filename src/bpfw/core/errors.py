"""Framework-specific errors for BPFW catalog mode."""


class BpfwError(RuntimeError):
    """Base error for BPFW runtime failures."""


class BlueprintLockedError(BpfwError, PermissionError):
    """Raised when a protected blueprint write is attempted while locked."""


class BlueprintMissingError(BpfwError, FileNotFoundError):
    """Raised when an operation requires a missing blueprint file."""
