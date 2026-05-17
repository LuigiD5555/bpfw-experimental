"""Runtime lock lease for temporary authority writes during interactive tools."""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Callable, Iterator

from bpfw.catalog.access_control import (
    authorize_blueprint_writes_for_tool,
    authorize_temporary_blueprint_unlock_for_tool,
)
from bpfw.core.errors import BlueprintLockedError
from bpfw.protection.authority import (
    get_authority_protection_status,
)

PROTECTED_RUNTIME_TOOLS = {"inspector", "editor", "planner"}
AUTO_APPROVED_RUNTIME_TOOLS = {"inspector", "editor"}


@dataclass(slots=True)
class RuntimeLockLease:
    """Lease metadata produced while a protected integration is running."""

    tool_name: str
    temporarily_unlocked: bool = False
    relock_warning: str | None = None


def _is_interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _prompt_unlock_confirmation(tool_name: str, input_func: Callable[[str], str]) -> bool:
    prompt = (
        f"{tool_name} needs temporary write access to bpfw/blueprint.yaml while it is running.\n"
        "Allow temporary unlock and auto re-lock on exit? [y/N]: "
    )
    reply = input_func(prompt).strip().lower()
    return reply in {"y", "yes"}


@contextmanager
def runtime_blueprint_write_lease(
    project_root: Path,
    tool_name: str,
    input_func: Callable[[str], str] = input,
) -> Iterator[RuntimeLockLease]:
    """Authorize temporary blueprint writes for one protected tool runtime."""

    lease = RuntimeLockLease(tool_name=tool_name)
    if tool_name not in PROTECTED_RUNTIME_TOOLS:
        yield lease
        return

    lock_state = get_authority_protection_status(project_root=project_root).status
    if lock_state in {"locked", "degraded"}:
        if tool_name not in AUTO_APPROVED_RUNTIME_TOOLS:
            if not _is_interactive_terminal():
                raise BlueprintLockedError(
                    "Blueprint is locked and this session is non-interactive. "
                    "Run in an interactive terminal to approve temporary unlock, or run bpfw unlock manually."
                )
            if not _prompt_unlock_confirmation(tool_name=tool_name, input_func=input_func):
                raise BlueprintLockedError(
                    "Blueprint remains locked. Temporary unlock permission was not granted."
                )
        lease.temporarily_unlocked = True

    with authorize_blueprint_writes_for_tool(tool_name=tool_name):
        with authorize_temporary_blueprint_unlock_for_tool(tool_name=tool_name):
            yield lease
