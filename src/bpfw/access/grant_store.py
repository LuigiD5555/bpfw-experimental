from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from bpfw.access.models import AccessGrant


class AccessGrantStore:
    """Persists and loads signed scoped authority access grants."""

    def save(self, project_root: Path, grant: AccessGrant) -> Path:
        output_directory = project_root / ".bpfw/access_grants"
        output_directory.mkdir(parents=True, exist_ok=True)
        output_path = output_directory / f"{grant.grant_id}.json"
        payload = {
            "grant_id": grant.grant_id,
            "request_id": grant.request_id,
            "resource_id": grant.resource_id,
            "resource_path": grant.resource_path,
            "operation": grant.operation,
            "scope": grant.scope,
            "granted_by": grant.granted_by,
            "created_at": grant.created_at.astimezone(timezone.utc).isoformat(),
            "expires_at": grant.expires_at.astimezone(timezone.utc).isoformat(),
            "signature": grant.signature,
        }
        output_path.write_text(f"{json.dumps(payload, indent=2, ensure_ascii=True)}\n", encoding="utf-8")
        return output_path

    def load(self, project_root: Path, grant_id: str) -> AccessGrant:
        payload = json.loads((project_root / ".bpfw/access_grants" / f"{grant_id}.json").read_text(encoding="utf-8"))
        return AccessGrant(
            grant_id=str(payload["grant_id"]),
            request_id=str(payload["request_id"]),
            resource_id=str(payload["resource_id"]),
            resource_path=str(payload["resource_path"]),
            operation=str(payload["operation"]),
            scope=str(payload["scope"]),
            granted_by=str(payload["granted_by"]),
            created_at=datetime.fromisoformat(str(payload["created_at"]).replace("Z", "+00:00")),
            expires_at=datetime.fromisoformat(str(payload["expires_at"]).replace("Z", "+00:00")),
            signature=str(payload["signature"]),
        )

    def list_active(self, project_root: Path) -> list[AccessGrant]:
        grants_directory = project_root / ".bpfw/access_grants"
        if not grants_directory.exists():
            return []
        now_utc = datetime.now(tz=timezone.utc)
        active_grants: list[AccessGrant] = []
        for entry_path in sorted(grants_directory.glob("*.json")):
            grant = self.load(project_root=project_root, grant_id=entry_path.stem)
            if grant.expires_at.astimezone(timezone.utc) >= now_utc:
                active_grants.append(grant)
        return active_grants

    def find_matching(self, project_root: Path, resource_id: str, operation: str, scope: str) -> AccessGrant | None:
        for grant in self.list_active(project_root=project_root):
            if grant.resource_id == resource_id and grant.operation == operation and grant.scope == scope:
                return grant
        return None
