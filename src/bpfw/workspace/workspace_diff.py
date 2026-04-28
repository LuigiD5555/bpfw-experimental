"""Workspace filesystem diff primitives."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bpfw.integrity.hash_provider import compute_sha256, read_file_size


_METADATA_FILES = {"SCOPE.yaml", "CONTEXT.md"}


@dataclass(slots=True, frozen=True)
class WorkspaceFileSnapshot:
    """Snapshot of one file inside workspace."""

    path: str
    sha256: str
    size: int



def collect_workspace_snapshots(workspace_root: Path) -> dict[str, WorkspaceFileSnapshot]:
    """Collect snapshots for all non-metadata workspace files."""

    snapshots: dict[str, WorkspaceFileSnapshot] = {}
    if not workspace_root.exists():
        return snapshots

    for file_path in sorted(workspace_root.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.parent == workspace_root and file_path.name in _METADATA_FILES:
            continue

        relative_path = file_path.relative_to(workspace_root).as_posix()
        snapshots[relative_path] = WorkspaceFileSnapshot(
            path=relative_path,
            sha256=compute_sha256(file_path),
            size=read_file_size(file_path),
        )

    return snapshots
