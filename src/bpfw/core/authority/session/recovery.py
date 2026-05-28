"""PURPOSE session recovery metadata helpers for pending unified authority sessions
DOMAIN  temporary blueprint sessions
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AuthoritySessionMeta:
    """PURPOSE structured metadata persisted for one interactive authority session
    DOMAIN  temporary blueprint sessions
    """

    tool_name: str
    status: str
    created_at: str
    updated_at: str
    temporary_path: str
    message: str | None = None


def utc_now_iso8601() -> str:
    """PURPOSE get the UTC timestamp in ISO-8601 format with timezone
    DOMAIN  temporary blueprint sessions
    """

    return datetime.now(timezone.utc).isoformat()


def write_session_meta(meta_path: Path, meta: AuthoritySessionMeta) -> None:
    """PURPOSE write authority session metadata YAML to disk
    DOMAIN  temporary blueprint sessions
    """

    import yaml

    meta_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "tool": meta.tool_name,
        "status": meta.status,
        "created_at": meta.created_at,
        "updated_at": meta.updated_at,
        "temporary_path": meta.temporary_path,
        "message": meta.message,
    }
    rendered_meta = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    meta_path.write_text(rendered_meta, encoding="utf-8")


def read_session_meta(meta_path: Path) -> AuthoritySessionMeta | None:
    """PURPOSE read authority session metadata YAML when present
    DOMAIN  temporary blueprint sessions
    """

    if not meta_path.exists():
        return None

    import yaml

    parsed_data = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    if not isinstance(parsed_data, dict):
        return None

    tool_name = str(parsed_data.get("tool", ""))
    status = str(parsed_data.get("status", "pending"))
    created_at = str(parsed_data.get("created_at", utc_now_iso8601()))
    updated_at = str(parsed_data.get("updated_at", utc_now_iso8601()))
    temporary_path = str(parsed_data.get("temporary_path", ""))
    message_value = parsed_data.get("message")
    message = str(message_value) if isinstance(message_value, str) else None
    return AuthoritySessionMeta(
        tool_name=tool_name,
        status=status,
        created_at=created_at,
        updated_at=updated_at,
        temporary_path=temporary_path,
        message=message,
    )
