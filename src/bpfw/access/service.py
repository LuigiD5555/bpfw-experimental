from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

from bpfw.access.authorization_policy import AccessAuthorizationPolicy
from bpfw.access.grant_store import AccessGrantStore
from bpfw.access.models import AccessGrant, AccessRequest
from bpfw.access.request_store import AccessRequestStore
from bpfw.access.signer import AccessGrantSigner
from bpfw.approval.os_auth import ApprovalRequestContext, DummyAuthBackend, SudoAuthBackend
from bpfw.authority.resources import AuthorityResourceRegistry
from bpfw.security.keyring import resolve_hmac_key


class AccessService:
    """Coordinates access request creation and grant issuance."""

    def __init__(
        self,
        request_store: AccessRequestStore | None = None,
        grant_store: AccessGrantStore | None = None,
        signer: AccessGrantSigner | None = None,
    ) -> None:
        self._request_store = request_store or AccessRequestStore()
        self._grant_store = grant_store or AccessGrantStore()
        self._signer = signer or AccessGrantSigner()

    def create_request(self, project_root: Path, resource_id: str, operation: str, scope: str, reason: str) -> AccessRequest:
        registry = AuthorityResourceRegistry()
        normalized_resource_id = "project_blueprint" if resource_id == "blueprint" else resource_id
        resource = next((item for item in registry.list_resources() if item.resource_id == normalized_resource_id), None)
        if resource is None:
            raise ValueError(f"Unknown authority resource: {resource_id}")
        created_at = datetime.now(tz=timezone.utc).replace(microsecond=0)
        request_id = self._next_id(project_root=project_root, directory_name="access_requests", prefix="access-request", created_at=created_at)
        request = AccessRequest(
            request_id=request_id,
            resource_id=resource.resource_id,
            resource_path=resource.path,
            operation=operation,
            scope=scope,
            reason=reason,
            created_at=created_at,
            status="pending",
        )
        self._request_store.save(project_root=project_root, request=request)
        return request

    def grant_request(self, project_root: Path, request_id: str, granted_by: str, duration_minutes: int) -> AccessGrant:
        request = self._request_store.load(project_root=project_root, request_id=request_id)
        if request.status != "pending":
            raise ValueError(f"Access request is not pending: {request_id}")
        if duration_minutes <= 0:
            raise ValueError("duration_minutes must be greater than zero")
        backend_name = os.getenv("BPFW_AUTH_BACKEND", "dummy").strip().lower() or "dummy"
        AccessAuthorizationPolicy().validate_backend(backend_name=backend_name)
        auth_backend = SudoAuthBackend() if backend_name == "sudo" else DummyAuthBackend()
        auth_decision = auth_backend.authorize(
            ApprovalRequestContext(
                request_id=request.request_id,
                resource_id=request.resource_id,
                action=request.operation,
                change_id="access-grant",
                expires_at="",
                diff_fingerprint="",
                project_root=project_root,
            )
        )
        if not auth_decision.approved:
            raise ValueError(f"Authorization failed: {auth_decision.reason}")
        created_at = datetime.now(tz=timezone.utc).replace(microsecond=0)
        grant_id = self._next_id(project_root=project_root, directory_name="access_grants", prefix="access-grant", created_at=created_at)
        expires_at = created_at + timedelta(minutes=duration_minutes)
        provisional_grant = AccessGrant(
            grant_id=grant_id,
            request_id=request.request_id,
            resource_id=request.resource_id,
            resource_path=request.resource_path,
            operation=request.operation,
            scope=request.scope,
            granted_by=granted_by or auth_decision.approved_by,
            created_at=created_at,
            expires_at=expires_at,
            signature="",
        )
        signature = self._signer.sign(provisional_grant, secret_key=self._load_signing_key(project_root=project_root))
        grant = AccessGrant(
            grant_id=provisional_grant.grant_id,
            request_id=provisional_grant.request_id,
            resource_id=provisional_grant.resource_id,
            resource_path=provisional_grant.resource_path,
            operation=provisional_grant.operation,
            scope=provisional_grant.scope,
            granted_by=provisional_grant.granted_by,
            created_at=provisional_grant.created_at,
            expires_at=provisional_grant.expires_at,
            signature=signature,
        )
        self._grant_store.save(project_root=project_root, grant=grant)
        request.status = "granted"
        self._request_store.save(project_root=project_root, request=request)
        return grant

    def _load_signing_key(self, project_root: Path) -> str:
        return resolve_hmac_key(
            project_root=project_root,
            purpose="access",
            env_var_names=["BPFW_ACCESS_HMAC_KEY", "BPFW_APPROVAL_HMAC_KEY", "BPFW_MANIFEST_HMAC_KEY"],
        )

    def _next_id(self, project_root: Path, directory_name: str, prefix: str, created_at: datetime) -> str:
        directory_path = project_root / ".bpfw" / directory_name
        date_token = created_at.strftime("%Y%m%d")
        if not directory_path.exists():
            return f"{prefix}-{date_token}-001"
        count = sum(1 for item in directory_path.glob(f"{prefix}-{date_token}-*.json"))
        return f"{prefix}-{date_token}-{count + 1:03d}"
