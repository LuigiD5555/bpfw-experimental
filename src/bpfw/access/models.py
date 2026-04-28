from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class AccessRequest:
    """Represents a human request to open scoped authority access."""

    request_id: str
    resource_id: str
    resource_path: str
    operation: str
    scope: str
    reason: str
    created_at: datetime
    status: str


@dataclass(slots=True)
class AccessGrant:
    """Represents a signed scoped authority access grant."""

    grant_id: str
    request_id: str
    resource_id: str
    resource_path: str
    operation: str
    scope: str
    granted_by: str
    created_at: datetime
    expires_at: datetime
    signature: str


@dataclass(slots=True)
class AccessVerificationResult:
    """Represents the result of validating authority access."""

    valid: bool
    grant_id: str | None
    reason: str
    recommendation: str
