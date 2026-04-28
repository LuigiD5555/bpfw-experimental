from __future__ import annotations

import os

from bpfw.authority.os_lock import OsLockError, OsLockProvider, select_os_lock_provider


class OsLockPolicyError(RuntimeError):
    """Raised when strong lock policy cannot be enforced."""


class OsLockPolicy:
    """Resolves strong-lock provider and enforces hard-lock-only policy."""

    def resolve_provider(self) -> OsLockProvider:
        selection = select_os_lock_provider()
        provider = selection.provider
        if provider.supports_strong_lock():
            return provider

        environment_name = (os.getenv("BPFW_ENV", "").strip().lower() or "protected")
        raise OsLockPolicyError(
            "BLOCK\n\n"
            "Strong OS lock is required but not available.\n\n"
            f"Platform: {selection.platform_name}\n"
            f"Provider: {provider.name}\n"
            f"Environment: {environment_name}\n\n"
            "Install/enable strong lock primitives (chattr/chflags/icacls) and retry."
        )

    def ensure_capability(self) -> None:
        try:
            self.resolve_provider()
        except (OsLockError, OsLockPolicyError) as error:
            raise OsLockPolicyError(str(error)) from error
