"""PURPOSE runtime lock lease for temporary authority writes during interactive tools
DOMAIN  framework core
"""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Callable, Iterator

from bpfw.core.catalog.access_control import (
    authorize_blueprint_writes_for_tool,
    authorize_temporary_blueprint_unlock_for_tool,
)
from bpfw.core.errors import BlueprintLockedError
from bpfw.core.protection.authority import (
    get_authority_protection_status,
)

PROTECTED_RUNTIME_TOOLS = {"init", "inspector", "editor", "planner"}


@dataclass(slots=True)
class RuntimeLockLease:
    """PURPOSE lease metadata produced while a protected tool is running
    DOMAIN  framework core
    """

    tool_name: str
    temporarily_unlocked: bool = False
    relock_warning: str | None = None


def _is_interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _prompt_unlock_confirmation(tool_name: str, input_func: Callable[[str], str]) -> bool:
    prompt = (
        f"{tool_name} needs temporary write access to BPFW authority files.\n"
        "This includes bpfw/blueprint.yaml, bpfw/, bpfw/blocks/, and included shards.\n"
        "Allow temporary write access and auto re-lock on exit? [y/N]: "
    )
    reply = input_func(prompt).strip().lower()
    return reply in {"y", "yes"}


@contextmanager
def runtime_blueprint_write_lease(
    project_root: Path,
    tool_name: str,
    input_func: Callable[[str], str] = input,
) -> Iterator[RuntimeLockLease]:
    """PURPOSE authorize temporary blueprint writes for one protected tool runtime
    DOMAIN  framework core
    """

    lease = RuntimeLockLease(tool_name=tool_name)
    if tool_name not in PROTECTED_RUNTIME_TOOLS:
        yield lease
        return

    lock_state = get_authority_protection_status(project_root=project_root).status

    if lock_state in {"locked", "degraded"}:
        if tool_name == "inspector" and not _is_interactive_terminal():
            lease.temporarily_unlocked = True
        else:
            if not _is_interactive_terminal():
                raise BlueprintLockedError(
                    "Blueprint authority writes are blocked in non-interactive mode. "
                    "Run this command in an interactive terminal."
                )
            if not _prompt_unlock_confirmation(tool_name=tool_name, input_func=input_func):
                raise BlueprintLockedError(
                    "Blueprint authority write permission was not granted."
                )
            lease.temporarily_unlocked = True

    with authorize_blueprint_writes_for_tool(tool_name=tool_name):
        with authorize_temporary_blueprint_unlock_for_tool(tool_name=tool_name):
            yield lease
