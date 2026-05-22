"""Transaction support for the authority patch engine.

Provides backup/rollback mechanics and the write context protocol
that the engine requires before applying any plan.
"""

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PatchWriteContext:
    """Explicit permission context required by ``AuthorityPatchEngine.apply``.

    The engine does **not** obtain write permission silently. The caller
    must provide a write context that declares which tool is authorized
    and whether guarded writes (temporary unlock) are permitted.

    Attributes:
        tool_name: Name of the tool requesting writes (e.g. ``"diff"``).
        allow_guarded_writes: Whether the context permits temporary
            authority unlock during the apply.
    """

    tool_name: str = ""
    allow_guarded_writes: bool = False

    def is_valid(self) -> bool:
        """Return whether this context has the minimum required fields.

        Returns:
            True when ``tool_name`` is non-empty.
        """
        return bool(self.tool_name.strip())


class TransactionBackup:
    """Create and manage file backups for rollback during patch apply.

    Backups are stored in a temporary directory under the project root.
    On rollback, files are restored from backups. On commit, backups
    are cleaned up.
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize the backup manager.

        Args:
            project_root: The project root directory.
        """
        self._project_root = project_root
        self._backup_dir = project_root / ".bpfw" / "patch_backup"
        self._backed_up: set[Path] = set()

    @property
    def backup_dir(self) -> Path:
        """Return the backup directory path."""
        return self._backup_dir

    @property
    def backed_up_files(self) -> set[Path]:
        """Return the set of project-relative paths that have backups."""
        return set(self._backed_up)

    def backup(self, relative_path: Path) -> None:
        """Create a backup of a file if it exists.

        If the file does not exist (e.g., it is about to be created),
        no backup is created but the path is tracked.

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
            List of project-relative paths that were restored.
        """
        restored: list[Path] = []
        for relative_path in self._backed_up:
            backup_target = self._backup_dir / relative_path
            original_target = self._project_root / relative_path

            if backup_target.exists():
                original_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_target, original_target)
                restored.append(relative_path)
            else:
                # File was created by the patch; remove it on rollback.
                if original_target.exists():
                    original_target.unlink()
                    restored.append(relative_path)

        return restored

    def commit(self) -> None:
        """Clean up backup files after a successful apply."""
        if self._backup_dir.exists():
            shutil.rmtree(self._backup_dir, ignore_errors=True)
        self._backed_up.clear()