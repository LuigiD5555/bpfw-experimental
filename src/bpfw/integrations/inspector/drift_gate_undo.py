"""Crash-safe in-session undo support for Drift Gate authority decisions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bpfw.core.atomic_io import atomic_write_text
from bpfw.core.authority.patch.transaction import TransactionBackup
from bpfw.integrations.inspector.drift_gate_models import DriftGateResult

_AUTHORITY_SUFFIXES = frozenset({".yaml", ".yml", ".toml"})
_RECOVERY_RELATIVE = Path(".bpfw") / "blueprint_engine_backup"


@dataclass(slots=True)
class DriftUndoSnapshot:
    """Reversible decision/session state captured before one review entry."""

    entry_index: int
    drift_state_data: dict[str, Any]
    result: DriftGateResult
    input_signature: str | None
    authority_files: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class AuthorityUndoResult:
    """Result of restoring an authority-file snapshot."""

    success: bool
    error: str | None = None
    recovery_preserved: bool = False


class DriftAuthorityUndo:
    """Capture and transactionally restore authoritative YAML/TOML files."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)

    def capture(self) -> dict[str, str]:
        """Capture authoritative YAML/TOML files, excluding recovery artifacts."""
        authority_root = self.project_root / ".bpfw"
        files: dict[str, str] = {}
        if not authority_root.exists():
            return files
        recovery_root = self.project_root / _RECOVERY_RELATIVE
        for path in sorted(authority_root.rglob("*")):
            if not path.is_file() or path.suffix not in _AUTHORITY_SUFFIXES:
                continue
            try:
                path.relative_to(recovery_root)
            except ValueError:
                pass
            else:
                continue
            try:
                relative = path.relative_to(self.project_root).as_posix()
                files[relative] = path.read_text(encoding="utf-8")
            except (OSError, ValueError):
                continue
        return files

    def restore(self, desired_files: dict[str, str]) -> AuthorityUndoResult:
        """Restore a snapshot transactionally using the shared recovery contract."""
        backup = TransactionBackup(self.project_root)
        current_files = self.capture()
        all_paths = sorted(set(current_files) | set(desired_files))
        try:
            backup.ensure_clean_start()
            for relative in all_paths:
                backup.backup(Path(relative))
        except (OSError, RuntimeError) as error:
            return AuthorityUndoResult(False, str(error), backup.has_pending_recovery())

        try:
            for relative in sorted(set(current_files) - set(desired_files)):
                target = self.project_root / relative
                if target.exists():
                    target.unlink()
            for relative, content in desired_files.items():
                atomic_write_text(self.project_root / relative, content)
        except BaseException as restore_error:
            try:
                backup.rollback()
            except BaseException as rollback_error:
                return AuthorityUndoResult(
                    False,
                    f"undo restore failed: {restore_error}; rollback failed: {rollback_error}",
                    True,
                )
            backup.commit()
            return AuthorityUndoResult(False, str(restore_error), False)

        backup.commit()
        return AuthorityUndoResult(True)
