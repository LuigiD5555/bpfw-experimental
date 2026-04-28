from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bpfw.access.verifier import AccessVerifier
from bpfw.authority.resources import AuthorityResourceRegistry


@dataclass(slots=True)
class AuthorityDecision:
    allowed: bool
    status: str
    message: str
    resource_id: str
    operation: str | None
    scope: str | None
    recommendation: str


class AuthorityPolicy:
    """Decides whether authority resources may be changed."""

    def __init__(self, registry: AuthorityResourceRegistry | None = None, access_verifier: AccessVerifier | None = None) -> None:
        self._registry = registry or AuthorityResourceRegistry()
        self._access_verifier = access_verifier or AccessVerifier()

    def evaluate_direct_change(self, project_root: Path, relative_path: str, operation: str | None, scope: str | None) -> AuthorityDecision:
        resource = self._registry.resolve_by_path(relative_path)
        if resource is None:
            return AuthorityDecision(True, "OK", "Path is not an authority resource.", "", operation, scope, "Continue verify pipeline.")

        if not operation:
            return AuthorityDecision(False, "BLOCK", "Direct authority edits are not allowed. Missing operation context.", resource.resource_id, operation, scope, "Use proposal flow or request scoped authority access.")
        if not scope:
            return AuthorityDecision(False, "BLOCK", "Direct authority edits are not allowed. Missing scope context.", resource.resource_id, operation, scope, "Use proposal flow or request scoped authority access.")

        access_result = self._access_verifier.verify(
            project_root=project_root,
            resource_id=resource.resource_id,
            operation=operation,
            scope=scope,
        )
        if not access_result.valid:
            return AuthorityDecision(False, "BLOCK", access_result.reason, resource.resource_id, operation, scope, access_result.recommendation)

        return AuthorityDecision(True, "OK", "Authority access grant validated.", resource.resource_id, operation, scope, "Continue verify pipeline.")
