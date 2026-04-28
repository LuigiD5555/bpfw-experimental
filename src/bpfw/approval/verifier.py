"""Approval validation and matching for locked-resource hardening."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from bpfw.approval.signer import ApprovalSigningError, verify_approval_signature


APPROVALS_RELATIVE_PATH = ".bpfw/approvals"


@dataclass(slots=True, frozen=True)
class ApprovalIssue:
    """Single approval validation issue."""

    code: str
    message: str
    severity: str
    recommendation: str
    file_path: str = ""


@dataclass(slots=True, frozen=True)
class ApprovalRecord:
    """Validated approval document data."""

    approval_id: str
    request_id: str
    change_id: str
    resource_id: str
    action: str
    approved_by: str
    expires_at: str
    diff_fingerprint: str
    signature: str
    file_path: str


@dataclass(slots=True)
class ApprovalsVerificationResult:
    """Aggregated approval verification output."""

    approvals: list[ApprovalRecord] = field(default_factory=list)
    issues: list[ApprovalIssue] = field(default_factory=list)


class ApprovalVerificationError(RuntimeError):
    """Raised for hard failures when reading approval storage."""


def approvals_dir(project_root: Path) -> Path:
    """Resolve approvals directory path."""

    return project_root / APPROVALS_RELATIVE_PATH


def _issue(code: str, message: str, severity: str, recommendation: str, file_path: str = "") -> ApprovalIssue:
    return ApprovalIssue(
        code=code,
        message=message,
        severity=severity,
        recommendation=recommendation,
        file_path=file_path,
    )


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_one_approval(file_path: Path) -> tuple[ApprovalRecord | None, list[ApprovalIssue]]:
    issues: list[ApprovalIssue] = []

    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, [
            _issue(
                code="APP004",
                message=f"Invalid JSON in approval file `{file_path.name}`",
                severity="block",
                recommendation="Regenerate approval using `bpfw approve <request_id>`",
                file_path=str(file_path),
            )
        ]

    if not isinstance(payload, dict):
        return None, [
            _issue(
                code="APP004",
                message=f"Approval file `{file_path.name}` must be a JSON object",
                severity="block",
                recommendation="Regenerate approval using `bpfw approve <request_id>`",
                file_path=str(file_path),
            )
        ]

    required_fields = (
        "approval_id",
        "request_id",
        "change_id",
        "resource_id",
        "action",
        "approved_by",
        "expires_at",
        "diff_fingerprint",
        "signature",
    )
    for field_name in required_fields:
        field_value = payload.get(field_name)
        if not isinstance(field_value, str) or not field_value.strip():
            issues.append(
                _issue(
                    code="APP004",
                    message=f"Approval file `{file_path.name}` missing `{field_name}`",
                    severity="block",
                    recommendation="Regenerate approval using `bpfw approve <request_id>`",
                    file_path=str(file_path),
                )
            )

    if issues:
        return None, issues

    signature_value = str(payload["signature"])
    signable_payload = {key: value for key, value in payload.items() if key != "signature"}
    try:
        signature_valid = verify_approval_signature(payload=signable_payload, signature=signature_value)
    except ApprovalSigningError as error:
        return None, [
            _issue(
                code="APP001",
                message=str(error),
                severity="block",
                recommendation="Set approval signing key before validating approvals",
                file_path=str(file_path),
            )
        ]

    if not signature_valid:
        return None, [
            _issue(
                code="APP002",
                message=f"Approval signature is invalid in `{file_path.name}`",
                severity="critical",
                recommendation="Regenerate approval with `bpfw approve <request_id>`",
                file_path=str(file_path),
            )
        ]

    expiration_datetime = _parse_datetime(str(payload["expires_at"]))
    if expiration_datetime is None:
        return None, [
            _issue(
                code="APP004",
                message=f"Approval `{payload['approval_id']}` has invalid `expires_at`",
                severity="block",
                recommendation="Use ISO datetime with timezone for expiration",
                file_path=str(file_path),
            )
        ]

    if expiration_datetime < datetime.now(tz=timezone.utc):
        return None, [
            _issue(
                code="APP003",
                message=f"Approval `{payload['approval_id']}` is expired",
                severity="block",
                recommendation="Create a new approval request and approve it again",
                file_path=str(file_path),
            )
        ]

    return (
        ApprovalRecord(
            approval_id=str(payload["approval_id"]),
            request_id=str(payload["request_id"]),
            change_id=str(payload["change_id"]),
            resource_id=str(payload["resource_id"]),
            action=str(payload["action"]),
            approved_by=str(payload["approved_by"]),
            expires_at=str(payload["expires_at"]),
            diff_fingerprint=str(payload["diff_fingerprint"]),
            signature=signature_value,
            file_path=str(file_path),
        ),
        [],
    )


def verify_all_approvals(project_root: Path) -> ApprovalsVerificationResult:
    """Load and validate all approval documents."""

    directory_path = approvals_dir(project_root=project_root)
    if not directory_path.exists():
        return ApprovalsVerificationResult(approvals=[], issues=[])

    if not directory_path.is_dir():
        raise ApprovalVerificationError(f"Approval directory path is not a directory: {directory_path}")

    approvals: list[ApprovalRecord] = []
    issues: list[ApprovalIssue] = []

    for entry_path in sorted(directory_path.glob("*.json")):
        approval_record, approval_issues = _parse_one_approval(entry_path)
        if approval_record is not None:
            approvals.append(approval_record)
        if approval_issues:
            issues.extend(approval_issues)

    return ApprovalsVerificationResult(approvals=approvals, issues=issues)


def find_matching_approval(
    *,
    project_root: Path,
    resource_id: str,
    action: str,
    diff_fingerprint: str,
) -> tuple[ApprovalRecord | None, list[ApprovalIssue]]:
    """Find one valid approval matching resource, action, and diff fingerprint."""

    verification_result = verify_all_approvals(project_root=project_root)
    for approval_record in verification_result.approvals:
        if approval_record.resource_id != resource_id:
            continue
        if approval_record.action != action:
            continue
        if approval_record.diff_fingerprint != diff_fingerprint:
            continue
        return approval_record, verification_result.issues

    return None, verification_result.issues
