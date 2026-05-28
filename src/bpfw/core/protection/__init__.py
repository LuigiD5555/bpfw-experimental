"""PURPOSE blueprint protection support for BPFW catalog mode
DOMAIN  framework core
"""

from bpfw.core.protection.authority import (
    ProtectedResource,
    ProtectionResult,
    get_authority_protection_status,
    lock_authority,
    resolve_bpfw_package_root,
    resolve_guard_files,
    resolve_project_blueprint_path,
    resolve_protected_resources,
    unlock_authority,
)
from bpfw.core.protection.capabilities import LockSupportResult, check_lock_support
from bpfw.core.protection.setup import run_protection_setup

__all__ = [
    "LockSupportResult",
    "ProtectedResource",
    "ProtectionResult",
    "check_lock_support",
    "get_authority_protection_status",
    "lock_authority",
    "resolve_bpfw_package_root",
    "resolve_guard_files",
    "resolve_project_blueprint_path",
    "resolve_protected_resources",
    "run_protection_setup",
    "unlock_authority",
]
