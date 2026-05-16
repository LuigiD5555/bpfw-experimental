"""Blueprint write access control for BPFW MVP Catalog Mode."""

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator

from bpfw.core.errors import BlueprintLockedError
from bpfw.protection.authority import get_authority_protection_status

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
    """Temporarily authorize one tool to write blueprint data in this runtime context."""

    current_tools = _AUTHORIZED_TOOLS.get()
    next_tools = set(current_tools)
    next_tools.add(tool_name)
    token = _AUTHORIZED_TOOLS.set(frozenset(next_tools))
    try:
        yield
    finally:
        _AUTHORIZED_TOOLS.reset(token)


def has_blueprint_write_authorization(tool_name: str | None = None) -> bool:
    """Return whether current runtime context has an active blueprint write authorization."""

    authorized_tools = _AUTHORIZED_TOOLS.get()
    if tool_name is None:
        return bool(authorized_tools)
    return tool_name in authorized_tools


@contextmanager
def authorize_temporary_blueprint_unlock_for_tool(tool_name: str) -> Iterator[None]:
    """Temporarily authorize one tool to unlock blueprint for a guarded write transaction."""

    current_tools = _TEMPORARY_UNLOCK_TOOLS.get()
    next_tools = set(current_tools)
    next_tools.add(tool_name)
    token = _TEMPORARY_UNLOCK_TOOLS.set(frozenset(next_tools))
    try:
        yield
    finally:
        _TEMPORARY_UNLOCK_TOOLS.reset(token)


def has_temporary_blueprint_unlock_authorization(tool_name: str | None = None) -> bool:
    """Return whether current runtime context can perform guarded temporary unlock."""

    authorized_tools = _TEMPORARY_UNLOCK_TOOLS.get()
    if tool_name is None:
        return bool(authorized_tools)
    return tool_name in authorized_tools

def ensure_blueprint_can_be_written(project_root: Path) -> None:
    """Raise when the MVP blueprint is locked against writes."""

    if has_blueprint_write_authorization():
        return

    if get_authority_protection_status(project_root=project_root).status in {"locked", "degraded"}:
        raise BlueprintLockedError("Blueprint is locked. Run bpfw unlock before editing.")
