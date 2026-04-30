"""OS-level file lock backend for BPFW MVP Catalog Mode."""

from pathlib import Path
import os
import shutil
import stat
import subprocess
import sys

LOCKED = "locked"
UNLOCKED = "unlocked"
UNKNOWN = "unknown"
UNSUPPORTED = "unsupported"


def _lock_path(project_root: Path) -> Path:
    return project_root / "bpfw" / ".lock"


def _can_use_sudo() -> bool:
    return sys.stdin.isatty() and shutil.which("sudo") is not None


def _run_privileged(command: list[str]) -> bool:
    if _is_root():
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0

    if not _can_use_sudo():
        return False

    result = subprocess.run(["sudo", *command], check=False)
    return result.returncode == 0


def _remove_write_bits(path: Path) -> None:
    current_mode = stat.S_IMODE(path.stat().st_mode)
    target_mode = current_mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH
    try:
        path.chmod(target_mode)
    except OSError:
        pass

    if stat.S_IMODE(path.stat().st_mode) != target_mode:
        _run_privileged(["chmod", f"{target_mode:o}", str(path)])


def _add_owner_write_bit(path: Path) -> None:
    current_mode = stat.S_IMODE(path.stat().st_mode)
    target_mode = current_mode | stat.S_IWUSR
    try:
        path.chmod(target_mode)
    except OSError:
        pass

    if stat.S_IMODE(path.stat().st_mode) != target_mode:
        _run_privileged(["chmod", f"{target_mode:o}", str(path)])


def _restore_mode(path: Path, mode: int | None) -> None:
    if mode is None:
        _add_owner_write_bit(path)
        return

    try:
        path.chmod(mode)
    except OSError:
        pass

    if stat.S_IMODE(path.stat().st_mode) != mode:
        _run_privileged(["chmod", f"{mode:o}", str(path)])


def _is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _has_any_write_bit(path: Path) -> bool:
    current_mode = stat.S_IMODE(path.stat().st_mode)
    return bool(current_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def _is_root_owned(path: Path) -> bool:
    path_stat = path.stat()
    return path_stat.st_uid == 0 and path_stat.st_gid == 0


def _chown_root(path: Path) -> bool:
    try:
        os.chown(path, 0, 0)
    except OSError:
        _run_privileged(["chown", "0:0", str(path)])
    return _is_root_owned(path)


def _restore_owner(path: Path, uid: int | None, gid: int | None) -> None:
    if uid is None or gid is None:
        return

    try:
        os.chown(path, uid, gid)
    except OSError:
        _run_privileged(["chown", f"{uid}:{gid}", str(path)])


def _try_set_immutable(path: Path) -> bool:
    return _try_chattr("+i", path)


def _try_clear_immutable(path: Path) -> bool:
    return _try_chattr("-i", path)


def _try_chattr(flag: str, path: Path) -> bool:
    if shutil.which("chattr") is None:
        return False

    result = subprocess.run(
        ["chattr", flag, str(path)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode == 0:
        return True

    return _run_privileged(["chattr", flag, str(path)])


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
) -> str:
    return (
        "locked: true\n"
        f"resource: {relative_path}\n"
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


def _remove_lock_marker(lock_path: Path) -> None:
    if not lock_path.exists():
        return

    try:
        lock_path.unlink()
    except OSError:
        _run_privileged(["rm", "-f", str(lock_path)])


def lock_file(project_root: Path, relative_path: str) -> str:
    """Lock a project-relative file against direct local writes."""

    target_path = project_root / relative_path
    if not target_path.exists():
        return UNKNOWN

    lock_path = _lock_path(project_root=project_root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    file_stat = target_path.stat()
    directory_stat = target_path.parent.stat()
    file_mode = stat.S_IMODE(file_stat.st_mode)
    directory_mode = stat.S_IMODE(directory_stat.st_mode)
    _remove_write_bits(target_path)
    file_immutable = _try_set_immutable(target_path)
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
            root_owned=_is_root() or _can_use_sudo(),
        ),
        encoding="utf-8",
    )
    _remove_write_bits(target_path.parent)
    _try_set_immutable(target_path.parent)
    _remove_write_bits(lock_path)
    _chown_root(target_path)
    _chown_root(lock_path)
    _chown_root(target_path.parent)

    if get_file_lock_state(project_root=project_root, relative_path=relative_path) == LOCKED:
        return LOCKED

    _restore_owner(target_path, file_stat.st_uid, file_stat.st_gid)
    _restore_owner(target_path.parent, directory_stat.st_uid, directory_stat.st_gid)
    _restore_mode(target_path.parent, directory_mode)
    _restore_mode(target_path, file_mode)
    _remove_lock_marker(lock_path)
    return UNSUPPORTED


def unlock_file(project_root: Path, relative_path: str) -> str:
    """Unlock a project-relative file for local writes."""

    target_path = project_root / relative_path
    if not target_path.exists():
        return UNKNOWN

    lock_path = _lock_path(project_root=project_root)
    _try_clear_immutable(target_path.parent)
    _try_clear_immutable(target_path)

    recorded_directory_mode = _read_recorded_mode(
        lock_path=lock_path,
        key="directory_mode",
    )
    recorded_file_mode = _read_recorded_mode(lock_path=lock_path, key="file_mode")
    recorded_directory_uid = _read_recorded_int(lock_path=lock_path, key="directory_uid")
    recorded_directory_gid = _read_recorded_int(lock_path=lock_path, key="directory_gid")
    recorded_file_uid = _read_recorded_int(lock_path=lock_path, key="file_uid")
    recorded_file_gid = _read_recorded_int(lock_path=lock_path, key="file_gid")

    _restore_owner(target_path, recorded_file_uid, recorded_file_gid)
    _restore_owner(target_path.parent, recorded_directory_uid, recorded_directory_gid)
    _restore_mode(target_path.parent, recorded_directory_mode)
    _restore_mode(target_path, recorded_file_mode)

    _remove_lock_marker(lock_path)

    return UNLOCKED


def get_file_lock_state(project_root: Path, relative_path: str) -> str:
    """Read whether a project-relative file is locked against writes."""

    target_path = project_root / relative_path
    if not target_path.exists():
        return UNKNOWN

    lock_path = _lock_path(project_root=project_root)
    if not lock_path.exists():
        return UNLOCKED

    content = lock_path.read_text(encoding="utf-8")
    expected_resource_line = f"resource: {relative_path}"
    if (
        "locked: true" in content
        and expected_resource_line in content
        and (
            (
                not _has_any_write_bit(target_path)
                and not _has_any_write_bit(target_path.parent)
            )
            or (
                _is_root_owned(target_path)
                and _is_root_owned(target_path.parent)
            )
        )
    ):
        return LOCKED
    return UNLOCKED
