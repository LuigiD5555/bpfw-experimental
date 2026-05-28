"""PURPOSE transaction support for Blueprint Engine file writes
DOMAIN  blueprint file changes
"""

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PatchWriteContext:
    """PURPOSE explicit permission context required by patch application
    DOMAIN  blueprint file changes
    """

    tool_name: str = ""
    allow_guarded_writes: bool = False

    def is_valid(self) -> bool:
        """PURPOSE check whether the context has the minimum required fields
        DOMAIN  blueprint file changes
        """
        return bool(self.tool_name.strip())


class TransactionBackup:
    """PURPOSE create and manage file backups for rollback during apply
    DOMAIN  blueprint file changes
    """

    def __init__(self, project_root: Path) -> None:
        """PURPOSE set up the backup manager
        DOMAIN  blueprint file changes
        """
        self._project_root = project_root
        self._backup_dir = project_root / ".bpfw" / "blueprint_engine_backup"
        self._backed_up: set[Path] = set()

    @property
    def backup_dir(self) -> Path:
        """PURPOSE get the backup directory path
        DOMAIN  blueprint file changes
        """
        return self._backup_dir

    @property
    def backed_up_files(self) -> set[Path]:
        """PURPOSE get backed-up project-relative files
        DOMAIN  blueprint file changes
        """
        return set(self._backed_up)

    def backup(self, relative_path: Path) -> None:
        """PURPOSE create a backup of a file if it exists
        DOMAIN  blueprint file changes
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
        """PURPOSE restore all backed-up files and remove newly created files
        DOMAIN  blueprint file changes
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
        """PURPOSE clean up backup files after a successful apply
        DOMAIN  blueprint file changes
        """
        if self._backup_dir.exists():
            shutil.rmtree(self._backup_dir, ignore_errors=True)
        self._backed_up.clear()
