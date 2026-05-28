"""PURPOSE blueprint write access control for BPFW catalog mode
DOMAIN  blueprint checks
"""

from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Iterator, TypeVar

from bpfw.core.errors import BlueprintLockedError
from bpfw.core.protection.authority import get_authority_protection_status

_Func = TypeVar("_Func", bound=Callable[..., object])

_AUTHORIZED_TOOLS: ContextVar[frozenset[str]] = ContextVar(
    "authorized_blueprint_write_tools",
    default=frozenset(),
)
_TEMPORARY_UNLOCK_TOOLS: ContextVar[frozenset[str]] = ContextVar(
    "temporary_blueprint_unlock_tools",
    default=frozenset(),
)


@contextmanager
def authorize_blueprint_writes_for_tool(tool_name: str) -> Iterator[None]:
    """PURPOSE temporarily authorize one tool to write blueprint data in this runtime context
    DOMAIN  blueprint checks
    """

    current_tools = _AUTHORIZED_TOOLS.get()
    next_tools = set(current_tools)
    next_tools.add(tool_name)
    token = _AUTHORIZED_TOOLS.set(frozenset(next_tools))
    try:
        yield
    finally:
        _AUTHORIZED_TOOLS.reset(token)


def has_blueprint_write_authorization(tool_name: str | None = None) -> bool:
    """PURPOSE check whether runtime context has an active blueprint write authorization
    DOMAIN  blueprint checks
    """

    authorized_tools = _AUTHORIZED_TOOLS.get()
    if tool_name is None:
        return bool(authorized_tools)
    return tool_name in authorized_tools


@contextmanager
def authorize_temporary_blueprint_unlock_for_tool(tool_name: str) -> Iterator[None]:
    """PURPOSE temporarily authorize one tool to unlock blueprint for a guarded write transaction
    DOMAIN  blueprint checks
    """

    current_tools = _TEMPORARY_UNLOCK_TOOLS.get()
    next_tools = set(current_tools)
    next_tools.add(tool_name)
    token = _TEMPORARY_UNLOCK_TOOLS.set(frozenset(next_tools))
    try:
        yield
    finally:
        _TEMPORARY_UNLOCK_TOOLS.reset(token)


def has_temporary_blueprint_unlock_authorization(tool_name: str | None = None) -> bool:
    """PURPOSE check whether runtime context can perform guarded temporary unlock
    DOMAIN  blueprint checks
    """

    authorized_tools = _TEMPORARY_UNLOCK_TOOLS.get()
    if tool_name is None:
        return bool(authorized_tools)
    return tool_name in authorized_tools


def ensure_blueprint_can_be_written(project_root: Path) -> None:
    """PURPOSE raise when the blueprint is locked against writes
    DOMAIN  blueprint checks
    """

    if (
        get_authority_protection_status(project_root=project_root).status in {"locked", "degraded"}
        and not has_temporary_blueprint_unlock_authorization()
    ):
        raise BlueprintLockedError("Blueprint is locked. Run bpfw unlock before editing.")


# ---------------------------------------------------------------------------
# Decorator-based authorization
# ---------------------------------------------------------------------------


def with_blueprint_write_auth(tool_name: str) -> Callable[[_Func], _Func]:
    """PURPOSE decorator that wraps a function call with blueprint write authorization
    DOMAIN  blueprint checks
    """

    def decorator(func: _Func) -> _Func:
        @wraps(func)
        def wrapper(*args: object, **kwargs: object) -> object:
            with authorize_blueprint_writes_for_tool(tool_name):
                return func(*args, **kwargs)
        return wrapper  # type: ignore[return-value]
    return decorator


def with_temporary_unlock(tool_name: str) -> Callable[[_Func], _Func]:
    """PURPOSE decorator that grants temporary blueprint unlock authorization
    DOMAIN  blueprint checks
    """

    def decorator(func: _Func) -> _Func:
        @wraps(func)
        def wrapper(*args: object, **kwargs: object) -> object:
            with authorize_blueprint_writes_for_tool(tool_name):
                with authorize_temporary_blueprint_unlock_for_tool(tool_name):
                    return func(*args, **kwargs)
        return wrapper  # type: ignore[return-value]
    return decorator
