"""Session recovery metadata helpers for pending unified authority sessions."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AuthoritySessionMeta:
    """Structured metadata persisted for one interactive authority session."""

    tool_name: str
    status: str
    created_at: str
    updated_at: str
    temporary_path: str
    message: str | None = None


def utc_now_iso8601() -> str:
    """Return the current UTC timestamp in ISO-8601 format with timezone."""

    return datetime.now(timezone.utc).isoformat()


def write_session_meta(meta_path: Path, meta: AuthoritySessionMeta) -> None:
    """Write authority session metadata YAML to disk.

    Args:
        meta_path: Absolute metadata YAML file path.
        meta: Session metadata payload.
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
    """Read authority session metadata YAML when present.

    Args:
        meta_path: Absolute metadata YAML file path.

    Returns:
        Parsed session metadata when available, otherwise None.
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
