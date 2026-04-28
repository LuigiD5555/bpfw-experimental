from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from bpfw.access.models import AccessRequest


class AccessRequestStore:
    """Persists and loads authority access requests."""

    def save(self, project_root: Path, request: AccessRequest) -> Path:
        output_directory = project_root / ".bpfw/access_requests"
        output_directory.mkdir(parents=True, exist_ok=True)
        output_path = output_directory / f"{request.request_id}.json"
        payload = {
            "request_id": request.request_id,
            "resource_id": request.resource_id,
            "resource_path": request.resource_path,
            "operation": request.operation,
            "scope": request.scope,
            "reason": request.reason,
            "created_at": request.created_at.astimezone(timezone.utc).isoformat(),
            "status": request.status,
        }
        output_path.write_text(f"{json.dumps(payload, indent=2, ensure_ascii=True)}\n", encoding="utf-8")
        return output_path

    def load(self, project_root: Path, request_id: str) -> AccessRequest:
        payload = json.loads((project_root / ".bpfw/access_requests" / f"{request_id}.json").read_text(encoding="utf-8"))
        return AccessRequest(
            request_id=str(payload["request_id"]),
            resource_id=str(payload["resource_id"]),
            resource_path=str(payload["resource_path"]),
            operation=str(payload["operation"]),
            scope=str(payload["scope"]),
            reason=str(payload["reason"]),
            created_at=datetime.fromisoformat(str(payload["created_at"]).replace("Z", "+00:00")),
            status=str(payload["status"]),
        )

    def list_pending(self, project_root: Path) -> list[AccessRequest]:
        requests_directory = project_root / ".bpfw/access_requests"
        if not requests_directory.exists():
            return []
        pending_requests: list[AccessRequest] = []
        for entry_path in sorted(requests_directory.glob("*.json")):
            request = self.load(project_root=project_root, request_id=entry_path.stem)
            if request.status == "pending":
                pending_requests.append(request)
        return pending_requests
