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

class AuthorityShardUnitOfWork:
    """Track shard mutations and save each changed shard once at commit time.

    This unit of work is intentionally scoped to one patch application. It keeps
    loaded shards in an identity map, lets operations mutate them in memory, and
    writes only the shards that actually changed after all operations succeed.
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize the shard unit of work.

        Args:
            project_root: Project root directory containing authority shard files.
        """
        self._project_root = project_root
        self._shards_by_path: dict[Path, object] = {}
        self._changed_paths: set[Path] = set()

    def load_shard(self, shard_path: Path, create_if_missing: bool = False):  # noqa: ANN201
        """Return one shard from the identity map, loading it when needed.

        Args:
            shard_path: Project-relative shard path.
            create_if_missing: Whether to create an in-memory empty shard if the
                file does not exist yet.

        Returns:
            Loaded authority shard.
        """
        normalized_path = Path(shard_path)
        cached_shard = self._shards_by_path.get(normalized_path)
        if cached_shard is not None:
            return cached_shard

        from bpfw.core.authority.shard import AuthorityShard

        absolute_path = self._project_root / normalized_path
        if absolute_path.exists():
            shard = AuthorityShard.load(self._project_root, normalized_path)
        elif create_if_missing:
            shard = AuthorityShard(path=normalized_path, blocks=[])
            self.mark_changed(normalized_path)
        else:
            shard = AuthorityShard.load(self._project_root, normalized_path)

        self._shards_by_path[normalized_path] = shard
        return shard

    def mark_changed(self, shard_path: Path) -> None:
        """Mark a shard as changed for the next commit.

        Args:
            shard_path: Project-relative shard path that should be saved.
        """
        self._changed_paths.add(Path(shard_path))

    def commit(self) -> list[Path]:
        """Persist all changed shards once.

        Returns:
            Changed project-relative shard paths that were written.
        """
        written_paths: list[Path] = []
        for shard_path in sorted(self._changed_paths):
            shard = self._shards_by_path.get(shard_path)
            if shard is None:
                continue
            shard.sort_blocks()
            shard.save(self._project_root)
            written_paths.append(shard_path)
        self._changed_paths.clear()
        return written_paths

    def has_changes(self) -> bool:
        """Return whether this unit of work has pending shard writes.

        Returns:
            True when at least one shard is marked as changed.
        """
        return bool(self._changed_paths)

