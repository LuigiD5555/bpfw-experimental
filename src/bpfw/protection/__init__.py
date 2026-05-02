"""Blueprint protection support for BPFW MVP Catalog Mode."""

from bpfw.protection.authority import (
    ProtectedResource,
    ProtectionResult,
    get_authority_lock_state,
    get_authority_protection_status,
    lock_authority,
    resolve_bpfw_package_root,
    resolve_guard_files,
    resolve_project_blueprint_path,
    resolve_protected_resources,
    unlock_authority,
)
from bpfw.protection.setup import run_protection_setup

__all__ = [
    "ProtectedResource",
    "ProtectionResult",
    "get_authority_lock_state",
    "get_authority_protection_status",
    "lock_authority",
    "resolve_bpfw_package_root",
    "resolve_guard_files",
    "resolve_project_blueprint_path",
    "resolve_protected_resources",
    "run_protection_setup",
    "unlock_authority",
]
