from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path


@dataclass(slots=True)
class AccessVerificationResult:
    valid: bool
    grant_id: str | None
    reason: str
    recommendation: str


class AccessVerifier:
    """Verifies active grants for authority resources."""

    def verify(
        self,
        *,
        project_root: Path,
        resource_id: str,
        resource_path: str,
        operation: str,
        scope: str,
    ) -> AccessVerificationResult:
        grants_dir = project_root / ".bpfw/access_grants"
        if not grants_dir.exists() or not grants_dir.is_dir():
            return AccessVerificationResult(False, None, "No active access grant was found.", "Use proposal flow or request scoped authority access.")

        for grant_file in sorted(grants_dir.glob("*.json")):
            try:
                payload = json.loads(grant_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue

            if str(payload.get("resource_id", "")).strip() != resource_id:
                continue
            if str(payload.get("resource_path", "")).strip() != resource_path:
                continue

            grant_operation = str(payload.get("operation", "")).strip()
            grant_scope = str(payload.get("scope", "")).strip()
            grant_id = str(payload.get("grant_id", "")).strip() or None

            if grant_operation != operation:
                return AccessVerificationResult(False, grant_id, "Access grant operation does not match requested operation.", "Request a new scoped authority grant with matching operation.")
            if grant_scope != scope:
                return AccessVerificationResult(False, grant_id, "Access grant scope does not match requested scope.", "Request a new scoped authority grant with matching scope.")

            expires_at = str(payload.get("expires_at", "")).strip()
            try:
                expiration = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).astimezone(timezone.utc)
            except ValueError:
                return AccessVerificationResult(False, grant_id, "Access grant expiration is invalid.", "Regenerate the access grant with a valid expiration datetime.")
            if expiration < datetime.now(tz=timezone.utc):
                return AccessVerificationResult(False, grant_id, "Access grant is expired.", "Request and approve a new scoped authority grant.")

            return AccessVerificationResult(True, grant_id, "Access grant is valid.", "Proceed with scoped authority change.")

        return AccessVerificationResult(False, None, "No active access grant was found.", "Use proposal flow or request scoped authority access.")
