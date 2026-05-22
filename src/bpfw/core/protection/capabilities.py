"""Capability detection for BPFW OS lock backends."""

from dataclasses import dataclass
from pathlib import Path
import ctypes
import os
import shutil
import stat
import subprocess
import sys
try:
    import pwd
except ImportError:  # pragma: no cover - not available on Windows
    pwd = None

from bpfw.core.protection.os_lock import DEGRADED, LOCKED, UNSUPPORTED

IMMUTABLE_BACKEND = "immutable"
OWNERSHIP_BACKEND = "ownership"
READONLY_WEAK_BACKEND = "readonly_weak"
WINDOWS_READONLY_BACKEND = "windows_readonly"
UNSUPPORTED_BACKEND = "unsupported"

WEAK_POSIX_LOCK_FILESYSTEMS = frozenset(
    {
        "exfat",
        "fuseblk",
        "msdos",
        "ntfs",
        "vfat",
    }
)


@dataclass(frozen=True, slots=True)
class LockSupportResult:
    """Describe whether the current project can enforce OS-level locks."""

    supported: bool
    status: str
    reason: str
    checked_path: Path
    backend: str = UNSUPPORTED_BACKEND


@dataclass(frozen=True, slots=True)
class MountContext:
    """Describe the mounted filesystem that contains a project path."""

    mount_point: Path
    filesystem_type: str


def _can_use_sudo() -> bool:
    """Return whether sudo can be invoked from the current terminal."""

    return sys.stdin.isatty() and shutil.which("sudo") is not None


def _is_root() -> bool:
    """Return whether the current process is running as root."""

    return hasattr(os, "geteuid") and os.geteuid() == 0


def _is_windows_admin() -> bool:
    """Return whether the current process has Windows administrator privileges."""

    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _decode_mount_field(value: str) -> str:
    """Decode escaped fields from Linux mountinfo."""

    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _find_mount_context(path: Path) -> MountContext | None:
    """Return Linux mount context for a path when mountinfo is available."""

    mountinfo_path = Path("/proc/self/mountinfo")
    if not mountinfo_path.exists():
        return None

    resolved_path = path.resolve()
    selected_context: MountContext | None = None
    selected_mount_length = -1

    try:
        mountinfo_lines = mountinfo_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    for mountinfo_line in mountinfo_lines:
        left_side, separator, right_side = mountinfo_line.partition(" - ")
        if not separator:
            continue

        left_fields = left_side.split()
        right_fields = right_side.split()
        if len(left_fields) < 5 or not right_fields:
            continue

        mount_point = Path(_decode_mount_field(left_fields[4]))
        filesystem_type = right_fields[0]
        try:
            path_is_inside_mount = (
                resolved_path == mount_point
                or resolved_path.is_relative_to(mount_point)
            )
        except ValueError:
            path_is_inside_mount = False

        if path_is_inside_mount and len(str(mount_point)) > selected_mount_length:
            selected_context = MountContext(
                mount_point=mount_point,
                filesystem_type=filesystem_type,
            )
            selected_mount_length = len(str(mount_point))

    return selected_context


def _does_not_support_strong_posix_lock(path: Path) -> bool:
    """Return whether a path is on a filesystem where strong POSIX locks are not trusted."""

    mount_context = _find_mount_context(path=path)
    if mount_context is None:
        return False
    return mount_context.filesystem_type.lower() in WEAK_POSIX_LOCK_FILESYSTEMS


def _format_unsupported_reason(project_root: Path) -> str:
    """Return a concrete unsupported-filesystem reason for init output."""

    mount_context = _find_mount_context(path=project_root)
    if mount_context is None:
        return (
            "The current filesystem or privilege context cannot enable immutable flags, "
            "root ownership protection, or read-only permission protection."
        )

    return (
        "The project path is on a "
        f"{mount_context.filesystem_type} filesystem mounted at {mount_context.mount_point}. "
        "This mount does not support strong POSIX authority protection, and read-only "
        "permission protection did not block normal writes."
    )


def _resolve_username(uid: int) -> str:
    """Resolve a username for a uid and fall back to the numeric uid."""

    if pwd is None:
        return str(uid)
    try:
        return pwd.getpwuid(uid).pw_name
    except (KeyError, OSError):
        return str(uid)


def _format_not_writable_reason(check_directory: Path) -> str:
    """Return a specific reason when the probe directory cannot be written."""

    base_reason = (
        "BPFW cannot probe lock support because the project path is not writable: "
        f"{check_directory}"
    )
    if not hasattr(os, "geteuid"):
        return base_reason

    check_parent = check_directory.parent
    try:
        parent_uid = check_parent.stat().st_uid
    except OSError:
        return base_reason

    current_uid = os.geteuid()
    if parent_uid == current_uid:
        return base_reason

    current_username = _resolve_username(uid=current_uid)
    owner_username = _resolve_username(uid=parent_uid)
    return (
        f"{base_reason}. "
        f"The directory {check_parent} is owned by {owner_username} while the current user is "
        f"{current_username}. "
        f"Repair with: sudo chown -R {current_username}:{current_username} {check_parent} && "
        f"chmod -R u+rwX {check_parent}"
    )


def _run_command(command: list[str]) -> bool:
    """Run a lock capability command without leaking backend output to the terminal."""

    if shutil.which(command[0]) is None:
        return False

    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False

    if result.returncode == 0:
        return True

    if _is_root():
        return False

    if not _can_use_sudo():
        return False

    try:
        privileged_result = subprocess.run(
            ["sudo", *command],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False

    return privileged_result.returncode == 0


def _run_immutable_command(platform_name: str, path: Path, enable: bool) -> bool:
    """Run the platform immutable-flag command against a temporary path."""

    if platform_name == "darwin":
        flag = "uchg" if enable else "nouchg"
        return _run_command(["chflags", flag, str(path)])

    if platform_name.startswith("linux"):
        flag = "+i" if enable else "-i"
        return _run_command(["chattr", flag, str(path)])

    return False


def _restore_mode(path: Path, mode: int) -> None:
    """Restore the original mode for a capability-check path."""

    try:
        path.chmod(mode)
    except OSError:
        _run_command(["chmod", f"{mode:o}", str(path)])


def _restore_owner(path: Path, uid: int, gid: int) -> None:
    """Restore the original owner for a capability-check path."""

    try:
        os.chown(path, uid, gid)
    except OSError:
        _run_command(["chown", f"{uid}:{gid}", str(path)])


def _has_any_write_bit(path: Path) -> bool:
    """Return whether a path has any POSIX write bit enabled."""

    current_mode = stat.S_IMODE(path.stat().st_mode)
    return bool(current_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def _is_root_owned(path: Path) -> bool:
    """Return whether a path is owned by root."""

    path_stat = path.stat()
    return path_stat.st_uid == 0 and path_stat.st_gid == 0


def _can_apply_readonly_weak_lock(check_path: Path, check_directory: Path) -> bool:
    """Return whether read-only permissions block normal writes."""

    file_mode = stat.S_IMODE(check_path.stat().st_mode)
    directory_mode = stat.S_IMODE(check_directory.stat().st_mode)
    readonly_file_mode = file_mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH
    readonly_directory_mode = directory_mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH

    try:
        check_path.chmod(readonly_file_mode)
        check_directory.chmod(readonly_directory_mode)
        readonly_bits_applied = not _has_any_write_bit(check_path) and not _has_any_write_bit(check_directory)
        if not readonly_bits_applied:
            return False
        try:
            check_path.write_text("readonly weak probe\n", encoding="utf-8")
        except OSError:
            return True
        return False
    except OSError:
        return False
    finally:
        _restore_mode(check_directory, directory_mode)
        _restore_mode(check_path, file_mode)


def _can_toggle_root_ownership(check_path: Path, check_directory: Path) -> bool:
    """Return whether root ownership can be applied and restored safely."""

    file_stat = check_path.stat()
    directory_stat = check_directory.stat()
    file_uid = file_stat.st_uid
    file_gid = file_stat.st_gid
    directory_uid = directory_stat.st_uid
    directory_gid = directory_stat.st_gid

    if not (_is_root() or _can_use_sudo()):
        return False

    file_changed = _run_command(["chown", "0:0", str(check_path)])
    directory_changed = _run_command(["chown", "0:0", str(check_directory)])
    ownership_applied = file_changed and directory_changed and _is_root_owned(check_path) and _is_root_owned(check_directory)

    _restore_owner(check_path, file_uid, file_gid)
    _restore_owner(check_directory, directory_uid, directory_gid)
    ownership_restored = (
        check_path.stat().st_uid == file_uid
        and check_path.stat().st_gid == file_gid
        and check_directory.stat().st_uid == directory_uid
        and check_directory.stat().st_gid == directory_gid
    )

    return ownership_applied and ownership_restored


def _check_posix_lock_support(project_root: Path, platform_name: str) -> LockSupportResult:
    """Check POSIX lock support using project-local temporary resources."""

    check_parent = project_root / "bpfw"
    check_directory = check_parent / ".lock_support_check_dir"
    check_path = check_directory / "resource.txt"
    try:
        check_directory.mkdir(parents=True, exist_ok=True)
        check_path.write_text("lock support check\n", encoding="utf-8")
    except OSError:
        return LockSupportResult(
            supported=False,
            status=UNSUPPORTED,
            reason=_format_not_writable_reason(check_directory=check_directory),
            checked_path=check_directory,
            backend=UNSUPPORTED_BACKEND,
        )
    immutable_attempted = False

    try:
        weak_posix_lock_filesystem = _does_not_support_strong_posix_lock(path=project_root)
        immutable_enabled = False
        if not weak_posix_lock_filesystem:
            immutable_attempted = True
            immutable_enabled = _run_immutable_command(
                platform_name=platform_name,
                path=check_path,
                enable=True,
            )
        if immutable_enabled:
            immutable_disabled = _run_immutable_command(
                platform_name=platform_name,
                path=check_path,
                enable=False,
            )
            if immutable_disabled:
                return LockSupportResult(
                    supported=True,
                    status=LOCKED,
                    reason="OS immutable flags are supported for this project path.",
                    checked_path=check_path,
                    backend=IMMUTABLE_BACKEND,
                )
            return LockSupportResult(
                supported=False,
                status=UNSUPPORTED,
                reason="The immutable flag could be enabled but could not be cleared safely.",
                checked_path=check_path,
                backend=IMMUTABLE_BACKEND,
            )

        if (
            not weak_posix_lock_filesystem
            and _can_toggle_root_ownership(check_path=check_path, check_directory=check_directory)
        ):
            return LockSupportResult(
                supported=True,
                status=LOCKED,
                reason="Root ownership protection is supported for this project path.",
                checked_path=check_path,
                backend=OWNERSHIP_BACKEND,
            )

        if _can_apply_readonly_weak_lock(check_path=check_path, check_directory=check_directory):
            return LockSupportResult(
                supported=True,
                status=DEGRADED,
                reason=(
                    "Strong OS protection is not available on this filesystem, but read-only "
                    "protection was enabled for local development."
                ),
                checked_path=check_path,
                backend=READONLY_WEAK_BACKEND,
            )

        return LockSupportResult(
            supported=False,
            status=UNSUPPORTED,
            reason=_format_unsupported_reason(project_root=project_root),
            checked_path=check_path,
            backend=UNSUPPORTED_BACKEND,
        )
    finally:
        if immutable_attempted:
            _run_immutable_command(platform_name=platform_name, path=check_path, enable=False)
        try:
            check_directory.chmod(stat.S_IRWXU)
        except OSError:
            pass
        try:
            check_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        try:
            check_path.unlink()
        except OSError:
            pass
        try:
            check_directory.rmdir()
        except OSError:
            pass


def _check_windows_lock_support(project_root: Path) -> LockSupportResult:
    """Check Windows read-only lock support using a temporary project-local file."""

    check_directory = project_root / "bpfw"
    check_path = check_directory / ".lock_support_check"
    try:
        check_directory.mkdir(parents=True, exist_ok=True)
        check_path.write_text("lock support check\n", encoding="utf-8")
    except OSError:
        return LockSupportResult(
            supported=False,
            status=UNSUPPORTED,
            reason=_format_not_writable_reason(check_directory=check_directory),
            checked_path=check_directory,
            backend=UNSUPPORTED_BACKEND,
        )

    try:
        current_mode = stat.S_IMODE(check_path.stat().st_mode)
        readonly_mode = current_mode & ~stat.S_IWUSR
        writable_mode = current_mode | stat.S_IWUSR
        check_path.chmod(readonly_mode)
        readonly = not bool(stat.S_IMODE(check_path.stat().st_mode) & stat.S_IWUSR)
        check_path.chmod(writable_mode)
        writable = bool(stat.S_IMODE(check_path.stat().st_mode) & stat.S_IWUSR)
        if readonly and writable:
            return LockSupportResult(
                supported=True,
                status=LOCKED,
                reason="Windows read-only attributes are supported for this project path.",
                checked_path=check_path,
                backend=WINDOWS_READONLY_BACKEND,
            )
        return LockSupportResult(
            supported=False,
            status=UNSUPPORTED,
            reason="The current Windows filesystem cannot toggle read-only attributes reliably.",
            checked_path=check_path,
            backend=UNSUPPORTED_BACKEND,
        )
    except OSError:
        return LockSupportResult(
            supported=False,
            status=UNSUPPORTED,
            reason="The current Windows filesystem rejected read-only attribute changes.",
            checked_path=check_path,
            backend=UNSUPPORTED_BACKEND,
        )
    finally:
        try:
            check_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        try:
            check_path.unlink()
        except OSError:
            pass


def check_lock_support(project_root: Path) -> LockSupportResult:
    """Check whether BPFW can enforce OS protection before mutating real resources."""

    resolved_root = project_root.resolve()
    platform_name = sys.platform

    if platform_name.startswith("linux") or platform_name == "darwin":
        return _check_posix_lock_support(
            project_root=resolved_root,
            platform_name=platform_name,
        )

    if platform_name == "win32":
        if not _is_windows_admin():
            return LockSupportResult(
                supported=False,
                status=UNSUPPORTED,
                reason="Windows authority locking requires an elevated terminal.",
                checked_path=resolved_root,
                backend=UNSUPPORTED_BACKEND,
            )
        return _check_windows_lock_support(project_root=resolved_root)

    return LockSupportResult(
        supported=False,
        status=UNSUPPORTED,
        reason=f"OS locking is not supported on platform: {platform_name}.",
        checked_path=resolved_root,
        backend=UNSUPPORTED_BACKEND,
    )
