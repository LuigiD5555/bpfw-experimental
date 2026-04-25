"""Permission helpers for catalog lock/unlock operations.

Implements Strategy pattern for cross-platform catalog protection:
- UnixImmutableStrategy: chattr +i (Linux - true immutable at filesystem level)
- WindowsAclStrategy: icacls /deny (Windows - access control lists)
- GitIndexStrategy: git update-index --assume-unchanged (NTFS/FUSE fallback)

Both strategies achieve real filesystem-level blocking, not just permissions.
"""

import os
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path
import stat


class CatalogLockStrategy(ABC):
    def __init__(self, paths: list[Path]) -> None:
        self.paths = paths

    @abstractmethod
    def lock(self) -> None:
        pass

    @abstractmethod
    def unlock(self) -> None:
        pass

    @abstractmethod
    def is_locked(self) -> bool:
        pass

    @abstractmethod
    def get_strategy_name(self) -> str:
        pass

    @abstractmethod
    def require_elevation(self) -> None:
        pass


class UnixImmutableStrategy(CatalogLockStrategy):
    def lock(self) -> None:
        chattr_path = shutil.which("chattr")
        if not chattr_path:
            raise RuntimeError("chattr not found: cannot lock catalog on this system")

        for path in self.paths:
            try:
                subprocess.run(
                    [chattr_path, "+i", str(path)],
                    check=True,
                    capture_output=True,
                )
            except (subprocess.CalledProcessError, OSError) as e:
                raise RuntimeError(f"Failed to lock {path}: {e}")

    def unlock(self) -> None:
        chattr_path = shutil.which("chattr")
        if not chattr_path:
            raise RuntimeError("chattr not found: cannot unlock catalog on this system")

        for path in self.paths:
            try:
                subprocess.run(
                    [chattr_path, "-i", str(path)],
                    check=True,
                    capture_output=True,
                )
            except (subprocess.CalledProcessError, OSError) as e:
                raise RuntimeError(f"Failed to unlock {path}: {e}")

    def is_locked(self) -> bool:
        if not self.paths:
            return True

        chattr_path = shutil.which("chattr")
        if not chattr_path:
            return True

        for path in self.paths:
            try:
                result = subprocess.run(
                    ["lsattr", str(path)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                if "i" not in result.stdout.split()[0]:
                    return False
            except (subprocess.CalledProcessError, OSError, IndexError):
                return False

        return True

    def get_strategy_name(self) -> str:
        return "linux-immutable"

    def require_elevation(self) -> None:
        if os.geteuid() != 0:
            print("This operation requires superuser privileges.")
            print("You will be prompted for your password.\n")
            environment = os.environ.copy()
            command = ["sudo", "-p", "[sudo] password for %u: ", sys.executable, __file__, *sys.argv[1:]]
            try:
                result = subprocess.run(command, env=environment, check=False)
            except KeyboardInterrupt:
                print("\nOperation cancelled.")
                raise SystemExit(1) from None
            raise SystemExit(result.returncode)


class WindowsAclStrategy(CatalogLockStrategy):
    def lock(self) -> None:
        username = os.getenv("USERNAME", "Everyone")
        for path in self.paths:
            try:
                subprocess.run(
                    ["icacls", str(path), "/deny", f"{username}:W"],
                    check=True,
                    capture_output=True,
                )
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass

    def unlock(self) -> None:
        username = os.getenv("USERNAME", "Everyone")
        for path in self.paths:
            try:
                subprocess.run(
                    ["icacls", str(path), "/remove:d", username],
                    check=True,
                    capture_output=True,
                )
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass

    def is_locked(self) -> bool:
        if not self.paths:
            return True
        username = os.getenv("USERNAME", "Everyone")
        for path in self.paths:
            try:
                result = subprocess.run(
                    ["icacls", str(path)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                if "(Deny)" in result.stdout and username in result.stdout:
                    return True
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass
        return False

    def get_strategy_name(self) -> str:
        return "windows-acl+admin"

    def require_elevation(self) -> None:
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            print("ERROR: This command requires administrator privileges")
            print("\nRun PowerShell as administrator and try again:")
            print("  Right-click PowerShell → 'Run as administrator'")
            print("  Then run: bpfw lock")
            raise SystemExit(1)


class GitIndexStrategy(CatalogLockStrategy):
    """Fallback strategy using git index for NTFS/FUSE filesystems.

    Uses 'git update-index --assume-unchanged' to prevent git from tracking changes.
    This works on NTFS and other filesystems where chmod is ignored.
    """

    def lock(self) -> None:
        for path in self.paths:
            try:
                subprocess.run(
                    ["git", "update-index", "--assume-unchanged", str(path)],
                    check=True,
                    capture_output=True,
                )
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                raise RuntimeError(f"Failed to lock {path} via git: {e}")

    def unlock(self) -> None:
        for path in self.paths:
            try:
                result = subprocess.run(
                    ["git", "update-index", "--no-assume-unchanged", str(path)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0 and "not in the index" not in result.stderr:
                    raise RuntimeError(f"Failed to unlock {path} via git: {result.stderr}")
            except FileNotFoundError as e:
                raise RuntimeError(f"git not found: {e}")

    def is_locked(self) -> bool:
        if not self.paths:
            return True

        for path in self.paths:
            try:
                result = subprocess.run(
                    ["git", "ls-files", "-v", str(path)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                if result.stdout and result.stdout[0] in ('h', 'S', 'M', 'K', 'T'):
                    continue
                return False
            except (subprocess.CalledProcessError, FileNotFoundError):
                return False

        return True

    def get_strategy_name(self) -> str:
        return "git-index"

    def require_elevation(self) -> None:
        pass


def _detect_ntfs(paths: list[Path]) -> bool:
    """Detect if any path is on an NTFS/FUSE filesystem."""
    if not paths:
        return False

    try:
        result = subprocess.run(
            ["df", "-T", str(paths[0])],
            check=True,
            capture_output=True,
            text=True,
        )
        for line in result.stdout.split("\n"):
            if "fuseblk" in line or "ntfs" in line.lower():
                return True
    except Exception:
        pass

    return False


def select_strategy(paths: list[Path]) -> CatalogLockStrategy:
    if sys.platform == "win32":
        return WindowsAclStrategy(paths)
    if _detect_ntfs(paths):
        return GitIndexStrategy(paths)
    return UnixImmutableStrategy(paths)

