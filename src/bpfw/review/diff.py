"""Workspace-vs-repository diff for change review."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bpfw.change.session import ChangeSession
from bpfw.integrity.hash_provider import compute_sha256, read_file_size
from bpfw.workspace.workspace_diff import collect_workspace_snapshots


@dataclass(slots=True, frozen=True)
class FileChange:
    """One file-level change candidate in workspace."""

    path: str
    change_type: str
    declared_in_scope: bool
    repo_exists: bool
    workspace_exists: bool
    repo_sha256: str
    workspace_sha256: str
    repo_size: int
    workspace_size: int


@dataclass(slots=True)
class ReviewDiffResult:
    """Computed diff result for one change session."""

    change_id: str
    workspace_path: str
    file_changes: list[FileChange] = field(default_factory=list)



def compute_review_diff(project_root: Path, session: ChangeSession) -> ReviewDiffResult:
    """Compare workspace and repository for declared scope files and additions."""

    workspace_root = project_root / session.workspace_relative_path
    allowed_paths = set(session.allowed_files)
    workspace_snapshots = collect_workspace_snapshots(workspace_root=workspace_root)

    file_changes: list[FileChange] = []

    for relative_path, workspace_snapshot in workspace_snapshots.items():
        repo_file_path = project_root / relative_path
        declared = relative_path in allowed_paths

        if repo_file_path.exists() and repo_file_path.is_file():
            repo_sha256 = compute_sha256(repo_file_path)
            repo_size = read_file_size(repo_file_path)
            if repo_sha256 == workspace_snapshot.sha256 and repo_size == workspace_snapshot.size:
                continue

            file_changes.append(
                FileChange(
                    path=relative_path,
                    change_type="modified",
                    declared_in_scope=declared,
                    repo_exists=True,
                    workspace_exists=True,
                    repo_sha256=repo_sha256,
                    workspace_sha256=workspace_snapshot.sha256,
                    repo_size=repo_size,
                    workspace_size=workspace_snapshot.size,
                )
            )
            continue

        file_changes.append(
            FileChange(
                path=relative_path,
                change_type="added",
                declared_in_scope=declared,
                repo_exists=False,
                workspace_exists=True,
                repo_sha256="",
                workspace_sha256=workspace_snapshot.sha256,
                repo_size=0,
                workspace_size=workspace_snapshot.size,
            )
        )

    for relative_path in sorted(allowed_paths):
        workspace_file_path = workspace_root / relative_path
        repo_file_path = project_root / relative_path
        if not repo_file_path.exists() or not repo_file_path.is_file():
            continue
        if workspace_file_path.exists() and workspace_file_path.is_file():
            continue

        file_changes.append(
            FileChange(
                path=relative_path,
                change_type="deleted",
                declared_in_scope=True,
                repo_exists=True,
                workspace_exists=False,
                repo_sha256=compute_sha256(repo_file_path),
                workspace_sha256="",
                repo_size=read_file_size(repo_file_path),
                workspace_size=0,
            )
        )

    return ReviewDiffResult(
        change_id=session.change_id,
        workspace_path=str(workspace_root),
        file_changes=sorted(file_changes, key=lambda item: item.path),
    )
