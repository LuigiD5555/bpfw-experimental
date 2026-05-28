"""PURPOSE framework-specific errors for BPFW catalog mode
DOMAIN  framework core
"""


class BpfwError(RuntimeError):
    """PURPOSE base error for BPFW runtime failures
    DOMAIN  framework core
    """


class BlueprintLockedError(BpfwError, PermissionError):
    """PURPOSE raised when a protected blueprint write is attempted while locked
    DOMAIN  framework core
    """


class BlueprintMissingError(BpfwError, FileNotFoundError):
    """PURPOSE raised when an operation requires a missing blueprint file
    DOMAIN  framework core
    """
