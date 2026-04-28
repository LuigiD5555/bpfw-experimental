"""OS authorization backends used by approval broker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import subprocess


@dataclass(slots=True, frozen=True)
class AuthDecision:
    """Result of an authorization attempt."""

    approved: bool
    backend: str
    approved_by: str
    reason: str


@dataclass(slots=True, frozen=True)
class ApprovalRequestContext:
    """Context presented to auth backend for approval."""

    request_id: str
    resource_id: str
    action: str
    change_id: str
    expires_at: str
    diff_fingerprint: str
    project_root: Path


class AuthBackend:
    """Minimal auth backend contract."""

    name: str = "base"

    def authorize(self, request_context: ApprovalRequestContext) -> AuthDecision:
        raise NotImplementedError


class DummyAuthBackend(AuthBackend):
    """Development backend that approves locally without OS prompts."""

    name = "dummy"

    def authorize(self, request_context: ApprovalRequestContext) -> AuthDecision:
        del request_context
        approver_name = os.getenv("BPFW_APPROVER_NAME", "").strip()
        if not approver_name:
            approver_name = os.getenv("USER", "").strip() or "local_owner"
        return AuthDecision(
            approved=True,
            backend=self.name,
            approved_by=approver_name,
            reason="Approved by dummy backend",
        )


class SudoAuthBackend(AuthBackend):
    """Basic sudo backend for Linux/macOS non-interactive auth checks."""

    name = "sudo"

    def authorize(self, request_context: ApprovalRequestContext) -> AuthDecision:
        del request_context
        system_name = platform.system().lower()
        if system_name not in {"linux", "darwin"}:
            return AuthDecision(
                approved=False,
                backend=self.name,
                approved_by="",
                reason="sudo backend is only supported on Linux/macOS",
            )

        process = subprocess.run(
            ["sudo", "-n", "true"],
            check=False,
            capture_output=True,
            text=True,
        )
        if process.returncode != 0:
            error_text = process.stderr.strip() or process.stdout.strip() or "sudo authorization failed"
            return AuthDecision(
                approved=False,
                backend=self.name,
                approved_by="",
                reason=error_text,
            )

        approver_name = os.getenv("SUDO_USER", "").strip() or os.getenv("USER", "").strip() or "local_owner"
        return AuthDecision(
            approved=True,
            backend=self.name,
            approved_by=approver_name,
            reason=f"Approved via sudo at {datetime.now(tz=timezone.utc).isoformat()}",
        )
