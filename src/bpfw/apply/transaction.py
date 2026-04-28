"""Transactional apply wrapper with rollback support."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import shutil
from pathlib import Path

from bpfw.apply.patcher import PatchApplyError, apply_file_changes
from bpfw.review.diff import FileChange


_TRANSACTIONS_RELATIVE_PATH = ".bpfw/transactions"


class ApplyTransactionError(RuntimeError):
    """Raised when transactional apply fails."""


@dataclass(slots=True, frozen=True)
class ApplyTransactionResult:
    """Result of transactional apply execution."""

    applied_paths: list[str]
    transaction_path: Path



def _transaction_root(project_root: Path, change_id: str) -> Path:
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
    return project_root / _TRANSACTIONS_RELATIVE_PATH / f"{change_id}-{timestamp}"


def _backup_paths(project_root: Path, backup_root: Path, file_changes: list[FileChange]) -> set[str]:
    existing_paths: set[str] = set()

    for file_change in file_changes:
        source_path = project_root / file_change.path
        if not source_path.exists() or not source_path.is_file():
            continue

        existing_paths.add(file_change.path)
        target_backup_path = backup_root / file_change.path
        target_backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_backup_path)

    return existing_paths


def _rollback_paths(project_root: Path, backup_root: Path, file_changes: list[FileChange], existing_paths: set[str]) -> None:
    changed_paths = {file_change.path for file_change in file_changes}

    for relative_path in sorted(existing_paths):
        backup_path = backup_root / relative_path
        destination_path = project_root / relative_path
        if not backup_path.exists():
            continue
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_path, destination_path)

    for relative_path in sorted(changed_paths):
        if relative_path in existing_paths:
            continue
        destination_path = project_root / relative_path
        if destination_path.exists() and destination_path.is_file():
            destination_path.unlink()


def apply_change_transaction(
    project_root: Path,
    workspace_root: Path,
    change_id: str,
    file_changes: list[FileChange],
) -> ApplyTransactionResult:
    """Apply change set transactionally with rollback on failure."""

    transaction_path = _transaction_root(project_root=project_root, change_id=change_id)
    backup_root = transaction_path / "backup"
    backup_root.mkdir(parents=True, exist_ok=False)

    existing_paths = _backup_paths(project_root=project_root, backup_root=backup_root, file_changes=file_changes)

    try:
        applied_paths = apply_file_changes(
            project_root=project_root,
            workspace_root=workspace_root,
            file_changes=file_changes,
        )
    except PatchApplyError as error:
        _rollback_paths(
            project_root=project_root,
            backup_root=backup_root,
            file_changes=file_changes,
            existing_paths=existing_paths,
        )
        raise ApplyTransactionError(str(error)) from error

    return ApplyTransactionResult(applied_paths=applied_paths, transaction_path=transaction_path)
