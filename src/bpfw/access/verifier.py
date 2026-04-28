from __future__ import annotations

from pathlib import Path

from bpfw.access.grant_store import AccessGrantStore
from bpfw.access.models import AccessVerificationResult
from bpfw.access.signer import AccessGrantSigner

from bpfw.security.keyring import resolve_hmac_key

class AccessVerifier:
    """Verifies scoped authority access before protected operations run."""

    def __init__(self, grant_store: AccessGrantStore | None = None, signer: AccessGrantSigner | None = None) -> None:
        self._grant_store = grant_store or AccessGrantStore()
        self._signer = signer or AccessGrantSigner()

    def verify(self, *, project_root: Path, resource_id: str, operation: str, scope: str) -> AccessVerificationResult:
        active_grants = self._grant_store.list_active(project_root=project_root)
        resource_grants = [item for item in active_grants if item.resource_id == resource_id]
        if not resource_grants:
            return AccessVerificationResult(False, None, "No active access grant was found.", "Use proposal flow or request scoped authority access.")
        operation_grants = [item for item in resource_grants if item.operation == operation]
        if not operation_grants:
            return AccessVerificationResult(False, resource_grants[0].grant_id, "Grant operation does not match requested operation.", "Request a new scoped authority grant with matching operation.")
        scope_grants = [item for item in operation_grants if item.scope == scope]
        if not scope_grants:
            return AccessVerificationResult(False, operation_grants[0].grant_id, "Grant scope does not match requested operation.", "Request a new scoped authority grant with matching scope.")
        signing_key = resolve_hmac_key(
            project_root=project_root,
            purpose="access",
            env_var_names=["BPFW_ACCESS_HMAC_KEY", "BPFW_APPROVAL_HMAC_KEY", "BPFW_MANIFEST_HMAC_KEY"],
        )
        for grant in scope_grants:
            if self._signer.verify(grant=grant, secret_key=signing_key):
                return AccessVerificationResult(True, grant.grant_id, "Access grant is valid.", "Proceed with scoped authority change.")
        return AccessVerificationResult(False, scope_grants[0].grant_id, "Access grant signature is invalid.", "Issue a new access grant and avoid manual grant file edits.")
