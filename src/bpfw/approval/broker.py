"""Approval broker orchestrating request auth and signed approval issuance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid

from bpfw.approval.os_auth import (
    ApprovalRequestContext,
    AuthDecision,
    DummyAuthBackend,
    SudoAuthBackend,
)
from bpfw.approval.request import ApprovalRequestRecord, load_approval_request
from bpfw.approval.signer import ApprovalSigningError, sign_approval_payload
from bpfw.approval.verifier import APPROVALS_RELATIVE_PATH


class ApprovalBrokerError(RuntimeError):
    """Raised when approval broker operations fail."""


@dataclass(slots=True, frozen=True)
class ApprovalWriteResult:
    """Output for approval write operation."""

    approval_id: str
    request_id: str
    file_path: Path
    approved_by: str
    backend: str


def _approvals_dir(project_root: Path) -> Path:
    return project_root / APPROVALS_RELATIVE_PATH


def _resolve_backend_name() -> str:
    return os.getenv("BPFW_APPROVAL_AUTH_BACKEND", "dummy").strip().lower() or "dummy"


def _build_backend():
    backend_name = _resolve_backend_name()
    if backend_name == "sudo":
        return SudoAuthBackend()
    return DummyAuthBackend()


def _authorize_request(project_root: Path, request_record: ApprovalRequestRecord) -> AuthDecision:
    backend = _build_backend()
    request_context = ApprovalRequestContext(
        request_id=request_record.request_id,
        resource_id=request_record.resource_id,
        action=request_record.action,
        change_id=request_record.change_id,
        expires_at=request_record.expires_at,
        diff_fingerprint=request_record.diff_fingerprint,
        project_root=project_root,
    )
    decision = backend.authorize(request_context=request_context)
    if decision.approved:
        return decision

    if backend.name == "sudo":
        fallback_backend = DummyAuthBackend()
        fallback_decision = fallback_backend.authorize(request_context=request_context)
        return AuthDecision(
            approved=fallback_decision.approved,
            backend=f"sudo->dummy",
            approved_by=fallback_decision.approved_by,
            reason=f"sudo unavailable ({decision.reason}); approved by dummy backend",
        )

    return decision


def approve_request(project_root: Path, request_id: str) -> ApprovalWriteResult:
    """Approve one request and persist signed approval record."""

    request_record = load_approval_request(project_root=project_root, request_id=request_id)
    decision = _authorize_request(project_root=project_root, request_record=request_record)
    if not decision.approved:
        raise ApprovalBrokerError(f"Approval rejected by backend `{decision.backend}`: {decision.reason}")

    approval_datetime = datetime.now(tz=timezone.utc).replace(microsecond=0)
    approval_id = f"approval-{approval_datetime.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    payload_without_signature = {
        "approval_id": approval_id,
        "request_id": request_record.request_id,
        "change_id": request_record.change_id,
        "resource_id": request_record.resource_id,
        "action": request_record.action,
        "approved_by": decision.approved_by,
        "expires_at": request_record.expires_at,
        "diff_fingerprint": request_record.diff_fingerprint,
    }
    try:
        signature_value = sign_approval_payload(payload=payload_without_signature)
    except ApprovalSigningError as error:
        raise ApprovalBrokerError(str(error)) from error

    serialized_payload = {
        **payload_without_signature,
        "signature": signature_value,
    }
    output_directory = _approvals_dir(project_root=project_root)
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / f"{approval_id}.json"
    output_path.write_text(f"{json.dumps(serialized_payload, indent=2, ensure_ascii=True)}\n", encoding="utf-8")

    return ApprovalWriteResult(
        approval_id=approval_id,
        request_id=request_record.request_id,
        file_path=output_path,
        approved_by=decision.approved_by,
        backend=decision.backend,
    )
