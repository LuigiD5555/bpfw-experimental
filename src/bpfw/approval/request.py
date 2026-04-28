"""Approval request persistence and diff fingerprint helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid


REQUESTS_RELATIVE_PATH = ".bpfw/approval_requests"
_DEFAULT_TTL_SECONDS = 24 * 60 * 60


class ApprovalRequestError(RuntimeError):
    """Raised when approval request operations fail."""


@dataclass(slots=True, frozen=True)
class ApprovalRequestRecord:
    """Canonical approval request model for locked-resource changes."""

    request_id: str
    change_id: str
    resource_id: str
    action: str
    requested_at: str
    expires_at: str
    diff_fingerprint: str

    def to_dict(self) -> dict[str, str]:
        return {
            "request_id": self.request_id,
            "change_id": self.change_id,
            "resource_id": self.resource_id,
            "action": self.action,
            "requested_at": self.requested_at,
            "expires_at": self.expires_at,
            "diff_fingerprint": self.diff_fingerprint,
        }


def approval_requests_dir(project_root: Path) -> Path:
    """Resolve approval request directory path."""

    return project_root / REQUESTS_RELATIVE_PATH


def request_file_path(project_root: Path, request_id: str) -> Path:
    """Resolve request file path by request id."""

    return approval_requests_dir(project_root=project_root) / f"{request_id}.json"


def compute_diff_fingerprint(
    *,
    path: str,
    expected_sha256: str,
    observed_sha256: str,
    expected_size: int,
    observed_size: int,
    action: str,
) -> str:
    """Build deterministic fingerprint for one file-level change."""

    payload = {
        "path": path,
        "action": action,
        "expected_sha256": expected_sha256,
        "observed_sha256": observed_sha256,
        "expected_size": expected_size,
        "observed_size": observed_size,
    }
    canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical_payload).hexdigest()


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ttl_seconds() -> int:
    raw_value = os.getenv("BPFW_APPROVAL_TTL_SECONDS", "").strip()
    if not raw_value:
        return _DEFAULT_TTL_SECONDS
    try:
        ttl_seconds = int(raw_value)
    except ValueError as error:
        raise ApprovalRequestError("BPFW_APPROVAL_TTL_SECONDS must be an integer") from error
    if ttl_seconds <= 0:
        raise ApprovalRequestError("BPFW_APPROVAL_TTL_SECONDS must be greater than zero")
    return ttl_seconds


def _load_request_if_exists(project_root: Path, request_id: str) -> ApprovalRequestRecord | None:
    path = request_file_path(project_root=project_root, request_id=request_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ApprovalRequestError(f"Invalid JSON in approval request {path}") from error
    if not isinstance(payload, dict):
        raise ApprovalRequestError(f"Approval request {path} must be a JSON object")

    required_fields = (
        "request_id",
        "change_id",
        "resource_id",
        "action",
        "requested_at",
        "expires_at",
        "diff_fingerprint",
    )
    for field_name in required_fields:
        field_value = payload.get(field_name)
        if not isinstance(field_value, str) or not field_value.strip():
            raise ApprovalRequestError(f"Approval request {path} missing `{field_name}`")

    return ApprovalRequestRecord(
        request_id=str(payload["request_id"]),
        change_id=str(payload["change_id"]),
        resource_id=str(payload["resource_id"]),
        action=str(payload["action"]),
        requested_at=str(payload["requested_at"]),
        expires_at=str(payload["expires_at"]),
        diff_fingerprint=str(payload["diff_fingerprint"]),
    )


def _find_existing_request(
    *,
    project_root: Path,
    resource_id: str,
    action: str,
    diff_fingerprint: str,
) -> ApprovalRequestRecord | None:
    request_directory = approval_requests_dir(project_root=project_root)
    if not request_directory.exists():
        return None

    now_utc = datetime.now(tz=timezone.utc)
    for entry_path in sorted(request_directory.glob("*.json")):
        request_id = entry_path.stem
        request_record = _load_request_if_exists(project_root=project_root, request_id=request_id)
        if request_record is None:
            continue
        if request_record.resource_id != resource_id or request_record.action != action:
            continue
        if request_record.diff_fingerprint != diff_fingerprint:
            continue

        expiration_datetime = _parse_datetime(request_record.expires_at)
        if expiration_datetime is None:
            continue
        if expiration_datetime < now_utc:
            continue
        return request_record

    return None


def load_approval_request(project_root: Path, request_id: str) -> ApprovalRequestRecord:
    """Load one request by identifier."""

    request_record = _load_request_if_exists(project_root=project_root, request_id=request_id)
    if request_record is None:
        raise ApprovalRequestError(f"Approval request does not exist: {request_id}")
    return request_record


def create_or_reuse_approval_request(
    *,
    project_root: Path,
    change_id: str,
    resource_id: str,
    action: str,
    diff_fingerprint: str,
) -> ApprovalRequestRecord:
    """Create request for one locked-resource modification or reuse existing one."""

    existing_request = _find_existing_request(
        project_root=project_root,
        resource_id=resource_id,
        action=action,
        diff_fingerprint=diff_fingerprint,
    )
    if existing_request is not None:
        return existing_request

    requested_at_datetime = datetime.now(tz=timezone.utc).replace(microsecond=0)
    expires_at_datetime = requested_at_datetime + timedelta(seconds=_ttl_seconds())

    request_id = f"request-{requested_at_datetime.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    request_record = ApprovalRequestRecord(
        request_id=request_id,
        change_id=change_id,
        resource_id=resource_id,
        action=action,
        requested_at=requested_at_datetime.isoformat(),
        expires_at=expires_at_datetime.isoformat(),
        diff_fingerprint=diff_fingerprint,
    )

    output_directory = approval_requests_dir(project_root=project_root)
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = request_file_path(project_root=project_root, request_id=request_id)
    output_path.write_text(f"{json.dumps(request_record.to_dict(), indent=2, ensure_ascii=True)}\n", encoding="utf-8")

    return request_record
