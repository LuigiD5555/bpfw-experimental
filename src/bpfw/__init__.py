"""Blueprint Framework (BPFW) package exports."""

__all__ = [
    "BlueprintEngine",
    "EngineResult",
    "ResultStatus",
    "StepResult",
]


def __getattr__(name: str):  # noqa: ANN001
    """Load top-level exports only when callers request them.

    Args:
        name: Export name requested from the package.

    Returns:
        Requested public export.

    Raises:
        AttributeError: If the requested name is not a supported export.
    """

    if name == "BlueprintEngine":
        from bpfw.core.engine import BlueprintEngine

        return BlueprintEngine
    if name in {"EngineResult", "ResultStatus", "StepResult"}:
        from bpfw.core.result import EngineResult, ResultStatus, StepResult

        exports = {
            "EngineResult": EngineResult,
            "ResultStatus": ResultStatus,
            "StepResult": StepResult,
        }
        return exports[name]
    raise AttributeError(f"module 'bpfw' has no attribute {name!r}")
