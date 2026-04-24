"""Catalog lock status reporting for BPFW."""

from bpfw.catalog.catalog_paths import (
    CatalogDirectoryNotFoundError,
    CatalogFilesNotFoundError,
    list_catalog_yaml_files,
)
from bpfw.catalog.file_permissions import verify_write_block
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

    try:
        guard_state = read_state_file()
        print(f"INFO: guard state: {guard_state['status']}")
        print(f"INFO: lock backend: {guard_state['lock_backend']}")
    except CatalogGuardStateFileNotFoundError:
        print("INFO: guard state: no state file (treat as unlocked)")
        guard_state = None
    except Exception as state_error:
        print(f"WARNING: cannot read guard state: {state_error}")
        guard_state = None

    state_status = guard_state["status"] if guard_state else "unlocked"
    write_block_active = verify_write_block(yaml_files)
    print(f"INFO: write block active: {write_block_active}")

    if state_status == "locked" and write_block_active:
        locked = list(yaml_files)
        unlocked = []
    else:
        locked = []
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
