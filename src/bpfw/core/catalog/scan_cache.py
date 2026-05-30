"""Incremental scan cache for inspector/editor workflows."""

import json
from pathlib import Path
from typing import Any

from bpfw.core.catalog.models import DiscoveredCodeUnit, ScanResult
from bpfw.core.catalog.review_order import order_blocks_for_review
from bpfw.core.catalog.scanner import _is_path_ignored, _scan_python_file
from bpfw.core.catalog.source_repository import SourceFileRepository
from bpfw.reports.finding import Finding

_SCHEMA_VERSION = 1
_CACHE_RELATIVE_PATH = Path(".bpfw") / "cache" / "scan_index.json"


class ScanCacheRepository:
    """Load and save an incremental source scan cache."""

    def __init__(self, project_root: Path) -> None:
        """Initialize the repository.

        Args:
            project_root: Project root directory.
        """
        self.project_root = project_root.resolve()
        self.cache_path = self.project_root / _CACHE_RELATIVE_PATH

    def load(self) -> dict[str, Any]:
        """Load cached scan data.

        Returns:
            Cache dictionary or an empty cache when missing/invalid.
        """
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return _empty_cache()
        if not isinstance(data, dict) or data.get("schema_version") != _SCHEMA_VERSION:
            return _empty_cache()
        entries = data.get("entries")
        if not isinstance(entries, dict):
            return _empty_cache()
        return data

    def save(self, cache_data: dict[str, Any]) -> None:
        """Save scan cache data.

        Args:
            cache_data: Cache dictionary to persist.
        """
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(cache_data, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def cached_scan_python_project(
    project_root: Path,
    source_roots: list[str],
    ignored_paths: list[str],
) -> ScanResult:
    """Scan Python project using per-file cached results and persist fresh entries.

    Args:
        project_root: Project root directory.
        source_roots: Source roots relative to project root.
        ignored_paths: Path components to ignore.

    Returns:
        Scan result built from cached and freshly scanned files.
    """
    return _scan_python_project_with_cache(
        project_root=project_root,
        source_roots=source_roots,
        ignored_paths=ignored_paths,
        write_cache=True,
    )


def read_only_cached_scan_python_project(
    project_root: Path,
    source_roots: list[str],
    ignored_paths: list[str],
) -> ScanResult:
    """Scan Python project using existing cache entries without writing cache files.

    Args:
        project_root: Project root directory.
        source_roots: Source roots relative to project root.
        ignored_paths: Path components to ignore.

    Returns:
        Scan result that reuses valid cache entries but leaves the filesystem unchanged.
    """
    return _scan_python_project_with_cache(
        project_root=project_root,
        source_roots=source_roots,
        ignored_paths=ignored_paths,
        write_cache=False,
    )


def _scan_python_project_with_cache(
    project_root: Path,
    source_roots: list[str],
    ignored_paths: list[str],
    write_cache: bool,
) -> ScanResult:
    """Scan a Python project with cache-aside behavior.

    Args:
        project_root: Project root directory.
        source_roots: Source roots relative to project root.
        ignored_paths: Path components to ignore.
        write_cache: Whether fresh scan entries should be persisted.

    Returns:
        Scan result built from cache hits and fresh source scans.
    """
    resolved_root = project_root.resolve()
    repository = ScanCacheRepository(resolved_root)
    source_repository = SourceFileRepository(resolved_root)
    cache_data = repository.load()
    old_entries = cache_data.get("entries", {}) if isinstance(cache_data.get("entries"), dict) else {}
    new_entries: dict[str, Any] = {}
    discovered_units: list[DiscoveredCodeUnit] = []
    findings: list[Finding] = []

    for source_root in source_roots:
        source_root_path = resolved_root / source_root
        if not source_root_path.exists() or not source_root_path.is_dir():
            continue
        for python_file in sorted(source_root_path.rglob("*.py")):
            relative_path = python_file.relative_to(resolved_root)
            if _is_path_ignored(relative_path, ignored_paths):
                continue
            relative_key = relative_path.as_posix()
            metadata = _file_metadata(python_file)
            old_entry = old_entries.get(relative_key)
            if _entry_matches(old_entry, metadata):
                units = [_unit_from_json(item) for item in old_entry.get("units", []) if isinstance(item, dict)]
                file_findings = [
                    _finding_from_json(item)
                    for item in old_entry.get("findings", [])
                    if isinstance(item, dict)
                ]
            else:
                units, file_findings = _scan_python_file(
                    resolved_root,
                    python_file,
                    relative_path,
                    source_repository=source_repository,
                )
            discovered_units.extend(units)
            findings.extend(file_findings)
            new_entries[relative_key] = {
                **metadata,
                "units": [_unit_to_json(unit) for unit in units],
                "findings": [_finding_to_json(finding) for finding in file_findings],
            }

    discovered_units = order_blocks_for_review(discovered_units)
    if write_cache:
        repository.save(
            {
                "schema_version": _SCHEMA_VERSION,
                "source_roots": list(source_roots),
                "ignored_paths": list(ignored_paths),
                "entries": new_entries,
            }
        )
    return ScanResult(
        discovered_units=discovered_units,
        findings=findings,
        source_repository=source_repository,
    )


def _empty_cache() -> dict[str, Any]:
    """Return an empty cache object.

    Returns:
        Empty cache dictionary.
    """
    return {"schema_version": _SCHEMA_VERSION, "entries": {}}


def _file_metadata(path: Path) -> dict[str, int]:
    """Return lightweight file metadata.

    Args:
        path: File path.

    Returns:
        Metadata dictionary.
    """
    stat_result = path.stat()
    return {"size": stat_result.st_size, "mtime_ns": stat_result.st_mtime_ns}


def _entry_matches(entry: Any, metadata: dict[str, int]) -> bool:
    """Check whether a cache entry matches current metadata."""
    if not isinstance(entry, dict):
        return False
    if entry.get("size") != metadata.get("size"):
        return False
    if entry.get("mtime_ns") != metadata.get("mtime_ns"):
        return False
    return isinstance(entry.get("units"), list) and isinstance(entry.get("findings"), list)


def _unit_to_json(unit: DiscoveredCodeUnit) -> dict[str, Any]:
    """Serialize one discovered code unit.

    Args:
        unit: Discovered code unit.

    Returns:
        JSON-compatible dictionary.
    """
    return {
        "path": unit.path,
        "module": unit.module,
        "symbol": unit.symbol,
        "symbol_type": unit.symbol_type,
        "qualified_name": unit.qualified_name,
        "start_line": unit.start_line,
        "end_line": unit.end_line,
        "methods": unit.methods,
        "functions": unit.functions,
        "imports": unit.imports,
        "decorators": unit.decorators,
        "docstring": unit.docstring,
        "signature": unit.signature,
        "interface_inputs": unit.interface_inputs,
        "interface_output": unit.interface_output,
        "calls": unit.calls,
        "normalized_body_hash": unit.normalized_body_hash,
        "dangerous_capabilities": unit.dangerous_capabilities,
    }


def _unit_from_json(data: dict[str, Any]) -> DiscoveredCodeUnit:
    """Restore one discovered code unit from JSON data.

    Args:
        data: JSON dictionary.

    Returns:
        Discovered code unit.
    """
    return DiscoveredCodeUnit(
        path=str(data.get("path", "")),
        module=str(data.get("module", "")),
        symbol=str(data.get("symbol", "")),
        symbol_type=str(data.get("symbol_type", "")),
        qualified_name=str(data.get("qualified_name", "")),
        start_line=_optional_int(data.get("start_line")),
        end_line=_optional_int(data.get("end_line")),
        methods=_string_list(data.get("methods")),
        functions=_string_list(data.get("functions")),
        imports=_string_list(data.get("imports")),
        decorators=_string_list(data.get("decorators")),
        docstring=_optional_string(data.get("docstring")),
        signature=_optional_string(data.get("signature")),
        interface_inputs=_dict_list(data.get("interface_inputs")),
        interface_output=data.get("interface_output") if isinstance(data.get("interface_output"), dict) else None,
        calls=_dict_list(data.get("calls")),
        normalized_body_hash=_optional_string(data.get("normalized_body_hash")),
        dangerous_capabilities=data.get("dangerous_capabilities")
        if isinstance(data.get("dangerous_capabilities"), dict)
        else {},
    )


def _finding_to_json(finding: Finding) -> dict[str, Any]:
    """Convert one finding."""
    return {
        "source": finding.source,
        "code": finding.code,
        "severity": finding.severity,
        "message": finding.message,
        "path": finding.path,
        "symbol": finding.symbol,
        "evidence": finding.evidence,
    }


def _finding_from_json(data: dict[str, Any]) -> Finding:
    """Restore one finding from JSON data.

    Args:
        data: JSON dictionary.

    Returns:
        Finding object.
    """
    evidence = data.get("evidence")
    return Finding(
        source=str(data.get("source", "bpfw")),
        code=str(data.get("code", "UNKNOWN")),
        severity=str(data.get("severity", "warning")),
        message=str(data.get("message", "")),
        path=_optional_string(data.get("path")),
        symbol=_optional_string(data.get("symbol")),
        evidence=evidence if isinstance(evidence, dict) else {},
    )


def _optional_int(value: Any) -> int | None:
    """Return an integer or None.

    Args:
        value: Candidate value.

    Returns:
        Integer or None.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _optional_string(value: Any) -> str | None:
    """Return a non-empty string or None.

    Args:
        value: Candidate value.

    Returns:
        Stripped string or None.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    """Return a list of strings.

    Args:
        value: Candidate value.

    Returns:
        String list.
    """
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    """Return a list of dictionaries.

    Args:
        value: Candidate value.

    Returns:
        Dictionary list.
    """
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]
