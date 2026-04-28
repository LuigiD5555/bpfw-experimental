"""Workspace construction utilities for scoped blueprint-first flow."""

from __future__ import annotations

import shutil
from pathlib import Path

from bpfw.change.session import ChangeSession
from bpfw.workspace.context_writer import write_context_file, write_scope_file


class WorkspaceBuildError(RuntimeError):
    """Raised when workspace creation fails."""


def build_workspace(project_root: Path, session: ChangeSession) -> Path:
    """Create workspace and copy only allowed files."""

    workspace_root = project_root / session.workspace_relative_path
    if workspace_root.exists():
        raise WorkspaceBuildError(f"Workspace already exists: {workspace_root}")

    workspace_root.mkdir(parents=True, exist_ok=False)

    for relative_path in session.allowed_files:
        source_path = project_root / relative_path
        if not source_path.exists() or not source_path.is_file():
            continue

        destination_path = workspace_root / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)

    write_scope_file(workspace_root=workspace_root, session=session)
    write_context_file(workspace_root=workspace_root, session=session)
    return workspace_root
