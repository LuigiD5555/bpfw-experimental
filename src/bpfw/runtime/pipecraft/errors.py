"""Errors raised by the managed PipeCraft runtime integration."""

class PipeCraftError(RuntimeError):
    """Base error for managed PipeCraft operations."""

class PipeCraftRuntimeError(PipeCraftError):
    """The bundled/managed PipeCraft runtime is missing or invalid."""

class PipeCraftExecutionError(PipeCraftError):
    """PipeCraft returned a failed process or malformed response."""
