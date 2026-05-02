"""Blueprint write access control for BPFW MVP Catalog Mode."""

from pathlib import Path

from bpfw.core.errors import BlueprintLockedError
from bpfw.protection.authority import get_authority_lock_state


def ensure_blueprint_can_be_written(project_root: Path) -> None:
    """Raise when the MVP blueprint is locked against writes."""

    if get_authority_lock_state(project_root=project_root) in {"locked", "degraded"}:
        raise BlueprintLockedError("Blueprint is locked. Run bpfw unlock before editing.")
