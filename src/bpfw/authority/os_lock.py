from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import platform
import shutil
import subprocess


class OsLockError(RuntimeError):
    """Raised when filesystem locking operations fail."""


class OsLockProvider:
    """Contract for strong filesystem lock operations."""

    name: str = "unknown"

    def supports_strong_lock(self) -> bool:
        raise NotImplementedError

    def lock(self, path: Path) -> None:
        raise NotImplementedError

    def unlock(self, path: Path) -> None:
        raise NotImplementedError

    def status(self, path: Path) -> str:
        raise NotImplementedError


class LinuxOsLockProvider(OsLockProvider):
    name = "linux-chattr"

    def supports_strong_lock(self) -> bool:
        return shutil.which("chattr") is not None and shutil.which("lsattr") is not None

    def lock(self, path: Path) -> None:
        self._run(["chattr", "+i", str(path)])

    def unlock(self, path: Path) -> None:
        self._run(["chattr", "-i", str(path)])

    def status(self, path: Path) -> str:
        try:
            output = subprocess.check_output(
                ["lsattr", "-d", str(path)],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except Exception:
            return "unknown"
        if output and " i " in f" {output} ":
            return "locked"
        return "unlocked"

    def _run(self, command: list[str]) -> None:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            error_text = (result.stderr or result.stdout or "operation failed").strip()
            raise OsLockError(f"OS lock command failed ({' '.join(command)}): {error_text}")


class MacOsLockProvider(OsLockProvider):
    name = "macos-chflags"

    def supports_strong_lock(self) -> bool:
        return shutil.which("chflags") is not None and shutil.which("ls") is not None

    def lock(self, path: Path) -> None:
        self._run(["chflags", "uchg", str(path)])

    def unlock(self, path: Path) -> None:
        self._run(["chflags", "nouchg", str(path)])

    def status(self, path: Path) -> str:
        result = subprocess.run(["ls", "-lO", str(path)], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return "unknown"
        output = result.stdout.strip()
        if " uchg " in f" {output} " or output.endswith(" uchg"):
            return "locked"
        return "unlocked"

    def _run(self, command: list[str]) -> None:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            error_text = (result.stderr or result.stdout or "operation failed").strip()
            raise OsLockError(f"OS lock command failed ({' '.join(command)}): {error_text}")


class WindowsOsLockProvider(OsLockProvider):
    name = "windows-icacls"

    def supports_strong_lock(self) -> bool:
        return os.name == "nt" and shutil.which("icacls") is not None

    def lock(self, path: Path) -> None:
        # Deny modify/write to everyone for strong lock behavior.
        self._run(["icacls", str(path), "/deny", "*S-1-1-0:(W,M)"])

    def unlock(self, path: Path) -> None:
        self._run(["icacls", str(path), "/remove:d", "*S-1-1-0"])

    def status(self, path: Path) -> str:
        result = subprocess.run(["icacls", str(path)], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return "unknown"
        output = result.stdout.upper()
        if "(DENY)" in output and ("(W)" in output or "(M)" in output):
            return "locked"
        return "unlocked"

    def _run(self, command: list[str]) -> None:
        result = subprocess.run(command, capture_output=True, text=True, check=False, shell=False)
        if result.returncode != 0:
            error_text = (result.stderr or result.stdout or "operation failed").strip()
            raise OsLockError(f"OS lock command failed ({' '.join(command)}): {error_text}")


@dataclass(slots=True, frozen=True)
class OsLockSelection:
    provider: OsLockProvider
    platform_name: str


def select_os_lock_provider() -> OsLockSelection:
    system_name = platform.system().lower()
    if system_name.startswith("linux"):
        return OsLockSelection(provider=LinuxOsLockProvider(), platform_name="linux")
    if system_name.startswith("darwin"):
        return OsLockSelection(provider=MacOsLockProvider(), platform_name="macos")
    if system_name.startswith("windows"):
        return OsLockSelection(provider=WindowsOsLockProvider(), platform_name="windows")
    raise OsLockError(f"Unsupported OS for hard lock policy: {system_name}")
