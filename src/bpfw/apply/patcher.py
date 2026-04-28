"""Patch application from workspace to repository."""

from __future__ import annotations

import shutil
from pathlib import Path

from bpfw.review.diff import FileChange


class PatchApplyError(RuntimeError):
    """Raised when workspace patch cannot be applied."""



def apply_file_changes(project_root: Path, workspace_root: Path, file_changes: list[FileChange]) -> list[str]:
    """Apply file changes from workspace into real repository."""

    applied_paths: list[str] = []

    for file_change in file_changes:
        destination_path = project_root / file_change.path
        source_path = workspace_root / file_change.path

        if file_change.change_type in {"modified", "added"}:
            if not source_path.exists() or not source_path.is_file():
                raise PatchApplyError(f"Workspace file missing while applying change: {file_change.path}")
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination_path)
            applied_paths.append(file_change.path)
            continue

        if file_change.change_type == "deleted":
            if destination_path.exists() and destination_path.is_file():
                destination_path.unlink()
                applied_paths.append(file_change.path)
            continue

        raise PatchApplyError(f"Unsupported change type `{file_change.change_type}` for {file_change.path}")

    return applied_paths
