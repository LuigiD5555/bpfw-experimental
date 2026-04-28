from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from bpfw.authority.operation import AuthorityOperation


class AuthorityAuditLog:
    """Records mechanical authority changes applied by BPFW."""

    def record(self, project_root: Path, operation: AuthorityOperation, grant_id: str) -> Path:
        output_path = project_root / ".bpfw/audit/authority-events.jsonl"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "event_type": "authority_change_applied",
            "resource_id": operation.resource_id,
            "operation": operation.operation_type,
            "scope": operation.scope,
            "grant_id": grant_id,
            "timestamp": datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat(),
        }
        with output_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True) + "\n")
        return output_path
