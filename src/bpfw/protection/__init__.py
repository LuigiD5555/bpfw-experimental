"""Blueprint protection support for BPFW MVP Catalog Mode."""

from bpfw.protection.authority import (
    ProtectedResource,
    ProtectionResult,
    get_authority_protection_status,
    get_blueprint_lock_state,
    lock_authority,
    lock_blueprint,
    resolve_bpfw_package_root,
    resolve_guard_files,
    resolve_project_blueprint_path,
    resolve_protected_resources,
    setup_blueprint_protection,
    unlock_authority,
    unlock_blueprint,
)
from bpfw.protection.setup import run_protection_setup

__all__ = [
    "ProtectedResource",
    "ProtectionResult",
    "get_authority_protection_status",
    "get_blueprint_lock_state",
    "lock_authority",
    "lock_blueprint",
    "resolve_bpfw_package_root",
    "resolve_guard_files",
    "resolve_project_blueprint_path",
    "resolve_protected_resources",
    "run_protection_setup",
    "setup_blueprint_protection",
    "unlock_authority",
    "unlock_blueprint",
]
