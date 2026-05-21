"""OS-level file lock backend for BPFW MVP Catalog Mode."""

from abc import ABC, abstractmethod
from pathlib import Path
import ctypes
import os
import shutil
import stat
import subprocess
import sys

LOCKED = "locked"
DEGRADED = "degraded"
UNLOCKED = "unlocked"
UNKNOWN = "unknown"
UNSUPPORTED = "unsupported"
MISSING = "missing"


def _lock_path(project_root: Path, relative_path: str) -> Path:
    if relative_path == "bpfw/blueprint.yaml":
        return project_root / "bpfw" / ".lock"

    safe_name = relative_path.replace("/", "__").replace("\\", "__")
    return project_root / "bpfw" / ".locks" / f"{safe_name}.lock"


def _lock_content(
    relative_path: str,
    file_mode: int,
    directory_mode: int,
    file_uid: int,
    file_gid: int,
    directory_uid: int,
    directory_gid: int,
    immutable: bool,
    root_owned: bool,
    backend: str,
    strong: bool,
) -> str:
    return (
        "locked: true\n"
        f"resource: {relative_path}\n"
        f"backend: {backend}\n"
        f"strong: {str(strong).lower()}\n"
        f"file_mode: {file_mode:o}\n"
        f"directory_mode: {directory_mode:o}\n"
        f"file_uid: {file_uid}\n"
        f"file_gid: {file_gid}\n"
        f"directory_uid: {directory_uid}\n"
        f"directory_gid: {directory_gid}\n"
        f"immutable: {str(immutable).lower()}\n"
        f"root_owned: {str(root_owned).lower()}\n"
    )


def _read_recorded_mode(lock_path: Path, key: str) -> int | None:
    if not lock_path.exists():
        return None

    for line in lock_path.read_text(encoding="utf-8").splitlines():
        field_name, separator, value = line.partition(":")
        if separator and field_name.strip() == key:
            try:
                return int(value.strip(), 8)
            except ValueError:
                return None
    return None


def _read_recorded_int(lock_path: Path, key: str) -> int | None:
    if not lock_path.exists():
        return None

    for line in lock_path.read_text(encoding="utf-8").splitlines():
        field_name, separator, value = line.partition(":")
        if separator and field_name.strip() == key:
            try:
                return int(value.strip())
            except ValueError:
                return None
    return None


def _read_recorded_text(lock_path: Path, key: str) -> str | None:
    if not lock_path.exists():
        return None

    for line in lock_path.read_text(encoding="utf-8").splitlines():
        field_name, separator, value = line.partition(":")
        if separator and field_name.strip() == key:
            return value.strip()
    return None


def _read_recorded_bool(lock_path: Path, key: str) -> bool:
    value = _read_recorded_text(lock_path=lock_path, key=key)
    return value == "true"


class LockStrategy(ABC):
    """Platform-specific locking strategy."""

    @abstractmethod
    def lock_file(self, project_root: Path, relative_path: str) -> str:
        """Lock a project-relative file against direct local writes."""

    @abstractmethod
    def unlock_file(self, project_root: Path, relative_path: str) -> str:
        """Unlock a project-relative file for local writes."""

    @abstractmethod
    def get_file_lock_state(self, project_root: Path, relative_path: str) -> str:
        """Read whether a project-relative file is locked against writes."""


class PosixLockStrategy(LockStrategy):
    """POSIX strategy for Linux and macOS."""

    def __init__(self, platform_name: str) -> None:
        self.platform_name = platform_name

    def lock_file(self, project_root: Path, relative_path: str) -> str:
        target_path = project_root / relative_path
        if not target_path.exists():
            return UNKNOWN
        existing_state = self.get_file_lock_state(project_root=project_root, relative_path=relative_path)
        if existing_state in {LOCKED, DEGRADED}:
            return existing_state

        lock_path = _lock_path(project_root=project_root, relative_path=relative_path)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        file_stat = target_path.stat()
        controlled_directory = self._controlled_directory_for(target_path)
        directory_stat = controlled_directory.stat()
        file_mode = stat.S_IMODE(file_stat.st_mode)
        directory_mode = stat.S_IMODE(directory_stat.st_mode)

        self._remove_write_bits(target_path)
        file_immutable = self._try_set_immutable(target_path)
        lock_path.write_text(
            _lock_content(
                relative_path=relative_path,
                file_mode=file_mode,
                directory_mode=directory_mode,
                file_uid=file_stat.st_uid,
                file_gid=file_stat.st_gid,
                directory_uid=directory_stat.st_uid,
                directory_gid=directory_stat.st_gid,
                immutable=file_immutable,
                root_owned=self._is_root() or self._can_use_sudo(),
                backend="strong",
                strong=True,
            ),
            encoding="utf-8",
        )
        self._remove_write_bits(controlled_directory)
        self._try_set_immutable(controlled_directory)
        self._remove_write_bits(lock_path)
        self._chown_root(target_path)
        self._chown_root(lock_path)
        self._chown_root(controlled_directory)

        if self.get_file_lock_state(project_root=project_root, relative_path=relative_path) == LOCKED:
            return LOCKED

        self._restore_owner(target_path, file_stat.st_uid, file_stat.st_gid)
        self._restore_owner(controlled_directory, directory_stat.st_uid, directory_stat.st_gid)
        self._restore_mode(controlled_directory, directory_mode)
        self._restore_mode(target_path, file_mode)
        self._remove_lock_marker(lock_path)
        return self._try_readonly_weak_lock(
            project_root=project_root,
            target_path=target_path,
            controlled_directory=controlled_directory,
            relative_path=relative_path,
            lock_path=lock_path,
            file_stat=file_stat,
            directory_stat=directory_stat,
            file_mode=file_mode,
            directory_mode=directory_mode,
        )

    def unlock_file(self, project_root: Path, relative_path: str) -> str:
        target_path = project_root / relative_path
        if not target_path.exists():
            return UNKNOWN

        lock_path = _lock_path(project_root=project_root, relative_path=relative_path)
        controlled_directory = self._controlled_directory_for(target_path)
        self._try_clear_immutable(controlled_directory)
        self._try_clear_immutable(target_path)

        recorded_directory_mode = _read_recorded_mode(lock_path=lock_path, key="directory_mode")
        recorded_file_mode = _read_recorded_mode(lock_path=lock_path, key="file_mode")
        recorded_directory_uid = _read_recorded_int(lock_path=lock_path, key="directory_uid")
        recorded_directory_gid = _read_recorded_int(lock_path=lock_path, key="directory_gid")
        recorded_file_uid = _read_recorded_int(lock_path=lock_path, key="file_uid")
        recorded_file_gid = _read_recorded_int(lock_path=lock_path, key="file_gid")

        self._restore_owner(target_path, recorded_file_uid, recorded_file_gid)
        self._restore_owner(controlled_directory, recorded_directory_uid, recorded_directory_gid)
        self._restore_mode(controlled_directory, recorded_directory_mode)
        self._restore_mode(target_path, recorded_file_mode)
        self._remove_lock_marker(lock_path)
        return UNLOCKED

    def get_file_lock_state(self, project_root: Path, relative_path: str) -> str:
        target_path = project_root / relative_path
        if not target_path.exists():
            return UNKNOWN

        lock_path = _lock_path(project_root=project_root, relative_path=relative_path)
        if not lock_path.exists():
            return UNLOCKED

        content = lock_path.read_text(encoding="utf-8")
        expected_resource_line = f"resource: {relative_path}"
        if "locked: true" not in content or expected_resource_line not in content:
            return UNLOCKED

        backend = _read_recorded_text(lock_path=lock_path, key="backend")
        controlled_directory = self._controlled_directory_for(target_path)
        if backend == "readonly_weak":
            if (
                not self._has_any_write_bit(target_path)
                and not self._has_any_write_bit(controlled_directory)
            ):
                return DEGRADED
            return UNLOCKED

        immutable_recorded = _read_recorded_bool(lock_path=lock_path, key="immutable")
        root_owned_recorded = _read_recorded_bool(lock_path=lock_path, key="root_owned")
        immutable_state_matches = immutable_recorded and not self._has_any_write_bit(target_path)
        root_owned_state_matches = (
            root_owned_recorded
            and self._is_root_owned(target_path)
            and self._is_root_owned(controlled_directory)
        )
        if immutable_state_matches or root_owned_state_matches:
            return LOCKED
        return UNLOCKED

    def _controlled_directory_for(self, target_path: Path) -> Path:
        return target_path if target_path.is_dir() else target_path.parent

    def _can_use_sudo(self) -> bool:
        return sys.stdin.isatty() and shutil.which("sudo") is not None

    def _run_privileged(self, command: list[str]) -> bool:
        if self._is_root():
            result = subprocess.run(
                command,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return result.returncode == 0

        if not self._can_use_sudo():
            return False

        try:
            result = subprocess.run(
                ["sudo", *command],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return False
        return result.returncode == 0

    def _remove_write_bits(self, path: Path) -> None:
        current_mode = stat.S_IMODE(path.stat().st_mode)
        target_mode = current_mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH
        try:
            path.chmod(target_mode)
        except OSError:
            pass

        if stat.S_IMODE(path.stat().st_mode) != target_mode:
            self._run_privileged(["chmod", f"{target_mode:o}", str(path)])

    def _add_owner_write_bit(self, path: Path) -> None:
        current_mode = stat.S_IMODE(path.stat().st_mode)
        target_mode = current_mode | stat.S_IWUSR
        try:
            path.chmod(target_mode)
        except OSError:
            pass

        if stat.S_IMODE(path.stat().st_mode) != target_mode:
            self._run_privileged(["chmod", f"{target_mode:o}", str(path)])

    def _restore_mode(self, path: Path, mode: int | None) -> None:
        if mode is None:
            self._add_owner_write_bit(path)
            return

        try:
            path.chmod(mode)
        except OSError:
            pass

        if stat.S_IMODE(path.stat().st_mode) != mode:
            self._run_privileged(["chmod", f"{mode:o}", str(path)])

    def _is_root(self) -> bool:
        return hasattr(os, "geteuid") and os.geteuid() == 0

    def _has_any_write_bit(self, path: Path) -> bool:
        current_mode = stat.S_IMODE(path.stat().st_mode)
        return bool(current_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))

    def _is_root_owned(self, path: Path) -> bool:
        path_stat = path.stat()
        return path_stat.st_uid == 0 and path_stat.st_gid == 0

    def _chown_root(self, path: Path) -> bool:
        try:
            os.chown(path, 0, 0)
        except OSError:
            self._run_privileged(["chown", "0:0", str(path)])
        return self._is_root_owned(path)

    def _restore_owner(self, path: Path, uid: int | None, gid: int | None) -> None:
        if uid is None or gid is None:
            return

        try:
            os.chown(path, uid, gid)
        except OSError:
            self._run_privileged(["chown", f"{uid}:{gid}", str(path)])

    def _try_set_immutable(self, path: Path) -> bool:
        if self.platform_name == "darwin":
            return self._try_command(["chflags", "uchg", str(path)])
        if self.platform_name.startswith("linux"):
            return self._try_command(["chattr", "+i", str(path)])
        return False

    def _try_clear_immutable(self, path: Path) -> bool:
        if self.platform_name == "darwin":
            return self._try_command(["chflags", "nouchg", str(path)])
        if self.platform_name.startswith("linux"):
            return self._try_command(["chattr", "-i", str(path)])
        return False

    def _try_command(self, command: list[str]) -> bool:
        if shutil.which(command[0]) is None:
            return False

        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            return True

        return self._run_privileged(command)

    def _try_readonly_weak_lock(
        self,
        project_root: Path,
        target_path: Path,
        controlled_directory: Path,
        relative_path: str,
        lock_path: Path,
        file_stat: os.stat_result,
        directory_stat: os.stat_result,
        file_mode: int,
        directory_mode: int,
    ) -> str:
        lock_path.write_text(
            _lock_content(
                relative_path=relative_path,
                file_mode=file_mode,
                directory_mode=directory_mode,
                file_uid=file_stat.st_uid,
                file_gid=file_stat.st_gid,
                directory_uid=directory_stat.st_uid,
                directory_gid=directory_stat.st_gid,
                immutable=False,
                root_owned=False,
                backend="readonly_weak",
                strong=False,
            ),
            encoding="utf-8",
        )
        self._remove_write_bits(target_path)
        self._remove_write_bits(controlled_directory)
        self._remove_write_bits(lock_path)

        if self.get_file_lock_state(project_root=project_root, relative_path=relative_path) == DEGRADED:
            return DEGRADED

        self._restore_mode(controlled_directory, directory_mode)
        self._restore_mode(target_path, file_mode)
        self._remove_lock_marker(lock_path)
        return UNSUPPORTED

    def _remove_lock_marker(self, lock_path: Path) -> None:
        if not lock_path.exists():
            return

        try:
            lock_path.unlink()
        except OSError:
            self._run_privileged(["rm", "-f", str(lock_path)])


class WindowsLockStrategy(LockStrategy):
    """Windows strategy using the native read-only attribute."""

    def lock_file(self, project_root: Path, relative_path: str) -> str:
        target_path = project_root / relative_path
        if not target_path.exists():
            return UNKNOWN
        if self.get_file_lock_state(project_root=project_root, relative_path=relative_path) == LOCKED:
            return LOCKED

        lock_path = _lock_path(project_root=project_root, relative_path=relative_path)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        file_stat = target_path.stat()
        directory_stat = target_path.parent.stat()
        lock_path.write_text(
            _lock_content(
                relative_path=relative_path,
                file_mode=stat.S_IMODE(file_stat.st_mode),
                directory_mode=stat.S_IMODE(directory_stat.st_mode),
                file_uid=file_stat.st_uid,
                file_gid=file_stat.st_gid,
                directory_uid=directory_stat.st_uid,
                directory_gid=directory_stat.st_gid,
                immutable=True,
                root_owned=self._is_admin(),
                backend="windows_readonly",
                strong=True,
            ),
            encoding="utf-8",
        )

        if not self._set_readonly(target_path, readonly=True):
            self._remove_lock_marker(lock_path)
            return UNSUPPORTED
        if not self._set_readonly(lock_path, readonly=True):
            self._set_readonly(target_path, readonly=False)
            self._remove_lock_marker(lock_path)
            return UNSUPPORTED
        if self.get_file_lock_state(project_root=project_root, relative_path=relative_path) == LOCKED:
            return LOCKED

        self._set_readonly(target_path, readonly=False)
        self._set_readonly(lock_path, readonly=False)
        self._remove_lock_marker(lock_path)
        return UNSUPPORTED

    def unlock_file(self, project_root: Path, relative_path: str) -> str:
        target_path = project_root / relative_path
        if not target_path.exists():
            return UNKNOWN

        lock_path = _lock_path(project_root=project_root, relative_path=relative_path)
        self._set_readonly(target_path, readonly=False)
        self._set_readonly(lock_path, readonly=False)
        self._remove_lock_marker(lock_path)
        return UNLOCKED

    def get_file_lock_state(self, project_root: Path, relative_path: str) -> str:
        target_path = project_root / relative_path
        if not target_path.exists():
            return UNKNOWN

        lock_path = _lock_path(project_root=project_root, relative_path=relative_path)
        if not lock_path.exists():
            return UNLOCKED

        content = lock_path.read_text(encoding="utf-8")
        expected_resource_line = f"resource: {relative_path}"
        if "locked: true" not in content or expected_resource_line not in content:
            return UNLOCKED
        if not self._is_readonly(target_path):
            return UNLOCKED
        return LOCKED

    def _set_readonly(self, path: Path, readonly: bool) -> bool:
        if not path.exists():
            return False

        current_mode = stat.S_IMODE(path.stat().st_mode)
        target_mode = current_mode & ~stat.S_IWUSR if readonly else current_mode | stat.S_IWUSR
        try:
            path.chmod(target_mode)
        except OSError:
            return False
        return self._is_readonly(path) if readonly else not self._is_readonly(path)

    def _is_readonly(self, path: Path) -> bool:
        return not bool(stat.S_IMODE(path.stat().st_mode) & stat.S_IWUSR)

    def _is_admin(self) -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False

    def _remove_lock_marker(self, lock_path: Path) -> None:
        if not lock_path.exists():
            return

        try:
            lock_path.unlink()
        except OSError:
            pass


class UnsupportedLockStrategy(LockStrategy):
    """Fallback strategy for unsupported platforms."""

    def lock_file(self, project_root: Path, relative_path: str) -> str:
        target_path = project_root / relative_path
        return UNKNOWN if not target_path.exists() else UNSUPPORTED

    def unlock_file(self, project_root: Path, relative_path: str) -> str:
        target_path = project_root / relative_path
        return UNKNOWN if not target_path.exists() else UNSUPPORTED

    def get_file_lock_state(self, project_root: Path, relative_path: str) -> str:
        target_path = project_root / relative_path
        return UNKNOWN if not target_path.exists() else UNLOCKED


def _build_lock_strategy(platform_name: str) -> LockStrategy:
    if platform_name.startswith("linux"):
        return PosixLockStrategy(platform_name=platform_name)
    if platform_name == "darwin":
        return PosixLockStrategy(platform_name=platform_name)
    if platform_name == "win32":
        return WindowsLockStrategy()
    return UnsupportedLockStrategy()


def _resolve_exact_lock_arguments(path: Path) -> tuple[Path, str]:
    """Resolve an exact file path into the lock strategy root and resource identifier."""

    resolved_path = path.resolve()
    if resolved_path.name == "blueprint.yaml" and resolved_path.parent.name == "bpfw":
        return resolved_path.parent.parent, "bpfw/blueprint.yaml"
    return resolved_path.parent, resolved_path.name


def _resolve_project_lock_arguments(project_root: Path, path: Path) -> tuple[Path, str]:
    """Resolve a file path into a project-rooted lock resource identifier."""

    resolved_root = project_root.resolve()
    resolved_path = path.resolve()
    try:
        relative_path = resolved_path.relative_to(resolved_root)
    except ValueError:
        return resolved_root, resolved_path.as_posix()
    return resolved_root, relative_path.as_posix()


def lock_file(path: Path) -> str:
    """Lock an exact file path against direct local writes."""

    if not path.exists():
        return MISSING

    resolved_root, resolved_relative_path = _resolve_exact_lock_arguments(path=path)
    return _build_lock_strategy(sys.platform).lock_file(
        project_root=resolved_root,
        relative_path=resolved_relative_path,
    )


def lock_project_file(project_root: Path, path: Path) -> str:
    """Lock a file while storing its marker under the project bpfw directory."""

    if not path.exists():
        return MISSING

    resolved_root, resolved_relative_path = _resolve_project_lock_arguments(
        project_root=project_root,
        path=path,
    )
    return _build_lock_strategy(sys.platform).lock_file(
        project_root=resolved_root,
        relative_path=resolved_relative_path,
    )


def unlock_file(path: Path) -> str:
    """Unlock an exact file path for local writes."""

    if not path.exists():
        return MISSING

    resolved_root, resolved_relative_path = _resolve_exact_lock_arguments(path=path)
    return _build_lock_strategy(sys.platform).unlock_file(
        project_root=resolved_root,
        relative_path=resolved_relative_path,
    )


def unlock_project_file(project_root: Path, path: Path) -> str:
    """Unlock a file whose marker is stored under the project bpfw directory."""

    if not path.exists():
        return MISSING

    resolved_root, resolved_relative_path = _resolve_project_lock_arguments(
        project_root=project_root,
        path=path,
    )
    return _build_lock_strategy(sys.platform).unlock_file(
        project_root=resolved_root,
        relative_path=resolved_relative_path,
    )


def get_file_lock_state(path: Path) -> str:
    """Read whether an exact file path is locked against writes."""

    if not path.exists():
        return MISSING

    resolved_root, resolved_relative_path = _resolve_exact_lock_arguments(path=path)
    return _build_lock_strategy(sys.platform).get_file_lock_state(
        project_root=resolved_root,
        relative_path=resolved_relative_path,
    )


def get_project_file_lock_state(project_root: Path, path: Path) -> str:
    """Read a file lock state from the project bpfw marker directory."""

    if not path.exists():
        return MISSING

    resolved_root, resolved_relative_path = _resolve_project_lock_arguments(
        project_root=project_root,
        path=path,
    )
    return _build_lock_strategy(sys.platform).get_file_lock_state(
        project_root=resolved_root,
        relative_path=resolved_relative_path,
    )
