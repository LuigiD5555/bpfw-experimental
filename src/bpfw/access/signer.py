from __future__ import annotations

import hashlib
import hmac
import json

from bpfw.access.models import AccessGrant


class AccessGrantSigner:
    """Signs and verifies scoped authority access grants."""

    def sign(self, grant: AccessGrant, secret_key: str) -> str:
        payload = self._canonical_payload(grant=grant)
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hmac.new(secret_key.encode("utf-8"), serialized, hashlib.sha256).hexdigest()

    def verify(self, grant: AccessGrant, secret_key: str) -> bool:
        expected = self.sign(grant=grant, secret_key=secret_key)
        return hmac.compare_digest(expected, grant.signature)

    def _canonical_payload(self, grant: AccessGrant) -> dict[str, str]:
        return {
            "grant_id": grant.grant_id,
            "request_id": grant.request_id,
            "resource_id": grant.resource_id,
            "resource_path": grant.resource_path,
            "operation": grant.operation,
            "scope": grant.scope,
            "granted_by": grant.granted_by,
            "created_at": grant.created_at.isoformat(),
            "expires_at": grant.expires_at.isoformat(),
        }
