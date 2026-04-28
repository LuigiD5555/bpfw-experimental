"""Workspace metadata writers for scope/context bootstrapping."""

from __future__ import annotations

from pathlib import Path

import yaml

from bpfw.change.session import ChangeSession


_SCOPE_FILE_NAME = "SCOPE.yaml"
_CONTEXT_FILE_NAME = "CONTEXT.md"


def write_scope_file(workspace_root: Path, session: ChangeSession) -> Path:
    """Write SCOPE.yaml to the workspace root."""

    scope_payload = {
        "change_id": session.change_id,
        "scope_resource_id": session.scope_resource_id,
        "scope_type": session.scope_type,
        "scope_locked": session.scope_locked,
        "allowed_files": session.allowed_files,
        "forbidden_duplicates": session.forbidden_duplicates,
    }
    output_path = workspace_root / _SCOPE_FILE_NAME
    output_path.write_text(yaml.safe_dump(scope_payload, sort_keys=False), encoding="utf-8")
    return output_path


def write_context_file(workspace_root: Path, session: ChangeSession) -> Path:
    """Write CONTEXT.md to the workspace root."""

    lines = [
        f"# Change Context: {session.change_id}",
        "",
        f"- Scope: `{session.scope_resource_id}` ({session.scope_type})",
        f"- Locked scope: `{str(session.scope_locked).lower()}`",
        "- Allowed files:",
    ]
    if session.allowed_files:
        lines.extend([f"  - `{path}`" for path in session.allowed_files])
    else:
        lines.append("  - `(none)`")

    if session.forbidden_duplicates:
        lines.append("- Forbidden duplicate names:")
        lines.extend([f"  - `{value}`" for value in session.forbidden_duplicates])

    output_path = workspace_root / _CONTEXT_FILE_NAME
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path
