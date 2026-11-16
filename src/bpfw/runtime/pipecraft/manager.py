"""Locate, install, verify and version the private PipeCraft runtime."""
from __future__ import annotations

import os
import platform as _platform
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from bpfw.runtime.pipecraft.errors import PipeCraftRuntimeError
from bpfw.runtime.pipecraft.integrity import parse_sha256_file, sha256_file
from bpfw.runtime.pipecraft.models import PipeCraftRuntimeInfo

PIPECRAFT_VERSION = "1.6.0-alpha.1"
PIPECRAFT_PLATFORM = "linux-x86_64"
DEV_OVERRIDE_ENV = "BPFW_PIPECRAFT_BIN"

@dataclass(slots=True)
class PipeCraftRuntimeManager:
    """Manage the PipeCraft binary shipped as part of BPFW."""
    data_root: Path | None = None

    def _package_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def bundled_binary(self) -> Path:
        return self._package_root() / "_runtime" / "pipecraft" / PIPECRAFT_VERSION / PIPECRAFT_PLATFORM / "pipecraft"

    def bundled_checksum(self) -> Path:
        return self.bundled_binary().with_name("pipecraft.sha256")

    def managed_root(self) -> Path:
        if self.data_root is not None:
            return self.data_root
        bpfw_home = os.environ.get("BPFW_HOME")
        if bpfw_home:
            return Path(bpfw_home).expanduser() / "runtimes"
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
        return base / "bpfw" / "runtimes"

    def managed_binary(self) -> Path:
        return self.managed_root() / "pipecraft" / PIPECRAFT_VERSION / PIPECRAFT_PLATFORM / "pipecraft"

    def expected_sha256(self) -> str:
        checksum = self.bundled_checksum()
        if not checksum.exists():
            raise PipeCraftRuntimeError(f"Bundled PipeCraft checksum is missing: {checksum}")
        return parse_sha256_file(checksum)

    def _validate_platform(self) -> None:
        machine = _platform.machine().lower()
        system = _platform.system().lower()
        if system != "linux" or machine not in {"x86_64", "amd64"}:
            raise PipeCraftRuntimeError(
                f"This BPFW build bundles PipeCraft for {PIPECRAFT_PLATFORM}; current platform is {system}-{machine}."
            )

    def _validate_binary(self, path: Path, expected_sha: str | None = None) -> None:
        if not path.is_file():
            raise PipeCraftRuntimeError(f"PipeCraft runtime is missing: {path}")
        if expected_sha is not None:
            actual = sha256_file(path)
            if actual.lower() != expected_sha.lower():
                raise PipeCraftRuntimeError(
                    f"PipeCraft integrity check failed for {path}. Expected {expected_sha}, got {actual}."
                )
        try:
            completed = subprocess.run(
                [str(path), "--version"], capture_output=True, text=True, check=False, timeout=10
            )
        except OSError as error:
            raise PipeCraftRuntimeError(f"PipeCraft runtime could not execute: {error}") from error
        if completed.returncode != 0:
            raise PipeCraftRuntimeError(completed.stderr.strip() or "PipeCraft --version failed.")
        expected_label = f"pipecraft {PIPECRAFT_VERSION}"
        if expected_label not in completed.stdout.strip():
            raise PipeCraftRuntimeError(
                f"Incompatible PipeCraft runtime. Expected {expected_label!r}, got {completed.stdout.strip()!r}."
            )

    def ensure_installed(self) -> PipeCraftRuntimeInfo:
        override = os.environ.get(DEV_OVERRIDE_ENV)
        if override:
            path = Path(override).expanduser().resolve()
            self._validate_binary(path, expected_sha=None)
            return PipeCraftRuntimeInfo(
                version=PIPECRAFT_VERSION,
                platform=PIPECRAFT_PLATFORM,
                path=path,
                sha256=sha256_file(path),
                managed=False,
            )

        self._validate_platform()
        bundled = self.bundled_binary()
        expected = self.expected_sha256()
        if not bundled.is_file():
            raise PipeCraftRuntimeError(f"Bundled PipeCraft runtime is missing: {bundled}")
        bundled_sha = sha256_file(bundled)
        if bundled_sha.lower() != expected.lower():
            raise PipeCraftRuntimeError(
                f"Bundled PipeCraft integrity check failed. Expected {expected}, got {bundled_sha}."
            )

        target = self.managed_binary()
        needs_copy = not target.exists()
        if target.exists():
            try:
                needs_copy = sha256_file(target).lower() != expected.lower()
            except OSError:
                needs_copy = True
        if needs_copy:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".tmp")
            shutil.copy2(bundled, temporary)
            temporary.chmod(temporary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            if sha256_file(temporary).lower() != expected.lower():
                temporary.unlink(missing_ok=True)
                raise PipeCraftRuntimeError("Copied PipeCraft runtime failed checksum verification.")
            temporary.replace(target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
        self._validate_binary(target, expected_sha=expected)
        return PipeCraftRuntimeInfo(
            version=PIPECRAFT_VERSION,
            platform=PIPECRAFT_PLATFORM,
            path=target,
            sha256=expected,
            managed=True,
        )
