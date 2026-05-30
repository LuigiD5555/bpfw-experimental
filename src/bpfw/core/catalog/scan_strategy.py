"""Scan strategies for read-only and cache-enabled project scans."""

from enum import Enum
from pathlib import Path
from typing import Protocol

from bpfw.core.catalog.models import ScanResult
from bpfw.core.catalog.scan_cache import (
    cached_scan_python_project,
    read_only_cached_scan_python_project,
)
from bpfw.core.catalog.scanner import scan_python_project


class ScanMode(Enum):
    """Supported project scan modes."""

    FULL_READ_ONLY = "full_read_only"
    READ_ONLY_CACHE = "read_only_cache"
    CACHE_ENABLED = "cache_enabled"


class ProjectScanStrategy(Protocol):
    """Protocol implemented by project scan strategies."""

    def scan(
        self,
        project_root: Path,
        source_roots: list[str],
        ignored_paths: list[str],
    ) -> ScanResult:
        """Scan a project and return discovered code units.

        Args:
            project_root: Root directory of the project.
            source_roots: Source roots relative to the project root.
            ignored_paths: Path components that should be ignored.

        Returns:
            Project scan result.
        """


class FullProjectScanStrategy:
    """Run a full read-only project scan."""

    def scan(
        self,
        project_root: Path,
        source_roots: list[str],
        ignored_paths: list[str],
    ) -> ScanResult:
        """Run a full scan without writing cache files.

        Args:
            project_root: Root directory of the project.
            source_roots: Source roots relative to the project root.
            ignored_paths: Path components that should be ignored.

        Returns:
            Project scan result.
        """
        return scan_python_project(
            project_root=project_root,
            source_roots=source_roots,
            ignored_paths=ignored_paths,
        )


class ReadOnlyCachedProjectScanStrategy:
    """Run a cache-aside scan without writing cache files."""

    def scan(
        self,
        project_root: Path,
        source_roots: list[str],
        ignored_paths: list[str],
    ) -> ScanResult:
        """Run a read-only scan that may reuse existing cache entries.

        Args:
            project_root: Root directory of the project.
            source_roots: Source roots relative to the project root.
            ignored_paths: Path components that should be ignored.

        Returns:
            Project scan result.
        """
        return read_only_cached_scan_python_project(
            project_root=project_root,
            source_roots=source_roots,
            ignored_paths=ignored_paths,
        )


class CachedProjectScanStrategy:
    """Run a cache-enabled project scan for mutable inspector workflows."""

    def scan(
        self,
        project_root: Path,
        source_roots: list[str],
        ignored_paths: list[str],
    ) -> ScanResult:
        """Run a cache-enabled project scan.

        Args:
            project_root: Root directory of the project.
            source_roots: Source roots relative to the project root.
            ignored_paths: Path components that should be ignored.

        Returns:
            Project scan result.
        """
        return cached_scan_python_project(
            project_root=project_root,
            source_roots=source_roots,
            ignored_paths=ignored_paths,
        )


class ProjectScanStrategyFactory:
    """Create project scan strategies from the requested scan mode."""

    def create(self, mode: ScanMode) -> ProjectScanStrategy:
        """Create a scan strategy for one scan mode.

        Args:
            mode: Scan mode requested by the caller.

        Returns:
            Project scan strategy for the requested mode.
        """
        if mode == ScanMode.FULL_READ_ONLY:
            return FullProjectScanStrategy()
        if mode == ScanMode.READ_ONLY_CACHE:
            return ReadOnlyCachedProjectScanStrategy()
        if mode == ScanMode.CACHE_ENABLED:
            return CachedProjectScanStrategy()
        raise ValueError(f"Unsupported scan mode: {mode}")
