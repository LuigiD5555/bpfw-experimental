from __future__ import annotations

import os

from bpfw.authority.os_lock import OsLockContext, OsLockError, OsLockStrategy, select_os_lock_strategy


class OsLockPolicyError(RuntimeError):
    """Raised when strong lock policy cannot be enforced."""


class OsLockPolicy:
    """Resolves strong-lock provider and enforces hard-lock-only policy."""

    def resolve_strategy(self) -> OsLockStrategy:
        selection = select_os_lock_strategy()
        strategy = selection.strategy
        if strategy.supports_strong_lock():
            return strategy

        environment_name = (os.getenv("BPFW_ENV", "").strip().lower() or "protected")
        raise OsLockPolicyError(
            "BLOCK\n\n"
            "Strong OS lock is required but not available.\n\n"
            f"Platform: {selection.platform_name}\n"
            f"Provider: {strategy.name}\n"
            f"Environment: {environment_name}\n\n"
            "Install/enable strong lock primitives (chattr/chflags/icacls) and retry."
        )

    def resolve_context(self) -> OsLockContext:
        return OsLockContext(strategy=self.resolve_strategy())

    def ensure_capability(self) -> None:
        try:
            self.resolve_strategy()
        except (OsLockError, OsLockPolicyError) as error:
            raise OsLockPolicyError(str(error)) from error
