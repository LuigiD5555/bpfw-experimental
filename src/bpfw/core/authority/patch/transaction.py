"""Transaction support for Blueprint Engine file-change writes."""

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PatchWriteContext:
    """Explicit permission context required by patch application.

    Attributes:
        tool_name: Name of the approved tool requesting writes.
        allow_guarded_writes: Whether temporary authority unlock is allowed.
    """

    tool_name: str = ""
    allow_guarded_writes: bool = False

    def is_valid(self) -> bool:
        """Return whether the context has the minimum required fields.

        Returns:
            True when ``tool_name`` is non-empty.
        """
        return bool(self.tool_name.strip())


class TransactionBackup:
    """Create and manage file backups for rollback during apply."""

    def __init__(self, project_root: Path) -> None:
        """Initialize the backup manager.

        Args:
            project_root: Project root directory.
        """
        self._project_root = project_root
        self._backup_dir = project_root / ".bpfw" / "blueprint_engine_backup"
        self._backed_up: set[Path] = set()

    def backup(self, relative_path: Path) -> None:
        """Create a backup of a file if it exists.

        Args:
            relative_path: Project-relative path to back up.
        """
        absolute_source = self._project_root / relative_path
        if relative_path in self._backed_up:
            return

        self._backed_up.add(relative_path)
        if not absolute_source.exists():
            return

        backup_target = self._backup_dir / relative_path
        backup_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(absolute_source, backup_target)

    def rollback(self) -> list[Path]:
        """Restore all backed-up files and remove newly created files.

        Returns:
            List of project-relative paths restored or removed.
        """
        restored: list[Path] = []
        for relative_path in self._backed_up:
            backup_target = self._backup_dir / relative_path
            original_target = self._project_root / relative_path

            if backup_target.exists():
                original_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_target, original_target)
                restored.append(relative_path)
            elif original_target.exists():
                original_target.unlink()
                restored.append(relative_path)

        return restored

    def commit(self) -> None:
        """Clean up backup files after a successful apply."""
        if self._backup_dir.exists():
            shutil.rmtree(self._backup_dir, ignore_errors=True)
        self._backed_up.clear()
