"""Catalog lock status reporting for BPFW."""

from pathlib import Path

from bpfw.catalog.catalog_paths import (
    CatalogDirectoryNotFoundError,
    CatalogFilesNotFoundError,
    list_catalog_yaml_files,
)
from bpfw.catalog.file_permissions import (
    detect_permission_enforcement_support,
    get_permissions_snapshot,
)
from bpfw.catalog.state_file import (
    CatalogGuardStateFileNotFoundError,
    read_state_file,
)


def status_catalog_command() -> int:
    """Report lock status for catalog YAML files."""
    try:
        yaml_files = list_catalog_yaml_files()
    except (CatalogDirectoryNotFoundError, CatalogFilesNotFoundError) as error:
        print(f"ERROR: {error}")
        return 1

    enforcement_supported = detect_permission_enforcement_support(yaml_files)
    if enforcement_supported:
        print("INFO: permission enforcement: chmod+state")
    else:
        print("INFO: permission enforcement: state-only (filesystem does not support chmod)")

    try:
        guard_state = read_state_file()
        print(f"INFO: guard state: {guard_state['status']}")
    except CatalogGuardStateFileNotFoundError:
        print("INFO: guard state: no state file (treat as unlocked)")
        guard_state = None
    except Exception as state_error:
        print(f"WARNING: cannot read guard state: {state_error}")
        guard_state = None

    locked: list[Path] = []
    unlocked: list[Path] = []
    if enforcement_supported:
        for yaml_file in yaml_files:
            if get_permissions_snapshot(yaml_file)["is_writable"]:
                unlocked.append(yaml_file)
            else:
                locked.append(yaml_file)
    else:
        state_status = guard_state["status"] if guard_state else "unlocked"
        if state_status == "locked":
            locked = list(yaml_files)
        else:
            unlocked = list(yaml_files)

    print(f"Total: {len(yaml_files)}")
    print(f"Locked: {len(locked)}")
    print(f"Unlocked: {len(unlocked)}")
    print()
    for yaml_file in locked:
        print(f"LOCKED: {yaml_file.name}")
    for yaml_file in unlocked:
        print(f"UNLOCKED: {yaml_file.name}")
    return 0

