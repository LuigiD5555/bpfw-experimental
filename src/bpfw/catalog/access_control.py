"""Blueprint write access control for BPFW MVP Catalog Mode."""

from pathlib import Path

from bpfw.core.errors import BlueprintLockedError
from bpfw.protection.authority import get_authority_protection_status


def ensure_blueprint_can_be_written(project_root: Path) -> None:
    """Raise when the MVP blueprint is locked against writes."""

    if get_authority_protection_status(project_root=project_root).status in {"locked", "degraded"}:
        raise BlueprintLockedError("Blueprint is locked. Run bpfw unlock before editing.")
