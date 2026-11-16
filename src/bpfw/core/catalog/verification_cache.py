"""Persistent cache for complete verification reports."""

import json
from pathlib import Path
from typing import Any

from bpfw.core.catalog.models import BlueprintLoadResult, VerificationReport
from bpfw.core.source.registry import iter_source_files
from bpfw.reports.finding import Finding

_SCHEMA_VERSION = 3
_ANALYZER_VERSION = "2026-10-post3-native-metadata-and-duplicate-precision-v4"
_CACHE_RELATIVE_PATH = Path(".bpfw") / "cache" / "verification_report.json"



def _load_fast_cached_verification_report(project_root: Path) -> tuple[VerificationReport, int] | None:
    """Return a cached report before loading the full sharded authority.

    Args:
        project_root: Root directory of the project being verified.

    Returns:
        Cached report and exit code, or None when the cache is unavailable or
        stale.
    """

    snapshot = _load_fast_cached_verification_snapshot(project_root=project_root)
    if snapshot is None:
        return None
    report, exit_code, _status_context = snapshot
    return report, exit_code


def _load_fast_cached_verification_snapshot(project_root: Path) -> tuple[VerificationReport, int, dict[str, Any]] | None:
    """Return cached report plus status context when all inputs are unchanged.

    This hot path uses the previous cache signature to know which source and
    authority files must be checked. When all file metadata still matches, the
    expensive shard load, source scan, and analyzer pipeline are skipped.

    Args:
        project_root: Root directory of the project being verified.

    Returns:
        Cached report, exit code, and status context, or None when stale.
    """

    resolved_root = project_root.resolve()
    cache_path = resolved_root / _CACHE_RELATIVE_PATH
    try:
        cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(cache_data, dict):
        return None
    previous_signature = cache_data.get("signature")
    if not isinstance(previous_signature, dict):
        return None
    source_roots = _string_list(previous_signature.get("source_roots"))
    ignored_paths = _string_list(previous_signature.get("ignored_paths"))
    authority_entries = previous_signature.get("authority_files")
    if not source_roots or not isinstance(authority_entries, list):
        return None
    authority_state = str(previous_signature.get("authority_state", "defined"))
    current_signature = {
        "schema_version": _SCHEMA_VERSION,
        "analyzer_version": _ANALYZER_VERSION,
        "authority_state": authority_state,
        "authority_revision": _authority_revision(resolved_root),
        "authority_files": _file_stat_signature(
            resolved_root,
            [resolved_root / str(entry.get("path", "")) for entry in authority_entries if isinstance(entry, dict)],
        ),
        "source_files": _file_stat_signature(resolved_root, _source_paths(resolved_root, source_roots, ignored_paths)),
        "source_roots": source_roots,
        "ignored_paths": ignored_paths,
    }
    if current_signature != previous_signature:
        return None
    report_data = cache_data.get("report")
    if not isinstance(report_data, dict):
        return None
    status_context = cache_data.get("status_context")
    if not isinstance(status_context, dict):
        status_context = {}
    try:
        report = _report_from_json(report_data)
    except (TypeError, ValueError):
        return None
    return report, 0 if report.allowed else 1, status_context

def _load_cached_verification_report(
    project_root: Path,
    load_result: BlueprintLoadResult,
    source_roots: list[str],
    ignored_paths: list[str],
) -> tuple[VerificationReport, int] | None:
    """Return a cached verification report when project inputs are unchanged.

    Args:
        project_root: Root directory of the project being verified.
        load_result: Already loaded blueprint authority.
        source_roots: Source roots used by the scanner.
        ignored_paths: Ignored path parts used by the scanner.

    Returns:
        Cached report and exit code, or None when the cache is missing, stale,
        or invalid.
    """

    resolved_root = project_root.resolve()
    cache_path = resolved_root / _CACHE_RELATIVE_PATH
    try:
        cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(cache_data, dict):
        return None
    current_signature = _build_cache_signature(
        project_root=resolved_root,
        load_result=load_result,
        source_roots=source_roots,
        ignored_paths=ignored_paths,
    )
    if cache_data.get("signature") != current_signature:
        return None
    report_data = cache_data.get("report")
    if not isinstance(report_data, dict):
        return None
    try:
        report = _report_from_json(report_data)
    except (TypeError, ValueError):
        return None
    exit_code = 0 if report.allowed else 1
    return report, exit_code


def _save_cached_verification_report(
    project_root: Path,
    load_result: BlueprintLoadResult,
    source_roots: list[str],
    ignored_paths: list[str],
    report: VerificationReport,
) -> None:
    """Persist a verification report for later unchanged command runs.

    Args:
        project_root: Root directory of the project being verified.
        load_result: Blueprint load result used to build the report.
        source_roots: Source roots used by the scanner.
        ignored_paths: Ignored path parts used by the scanner.
        report: Verification report to cache.
    """

    resolved_root = project_root.resolve()
    cache_path = resolved_root / _CACHE_RELATIVE_PATH
    cache_data = {
        "schema_version": _SCHEMA_VERSION,
        "signature": _build_cache_signature(
            project_root=resolved_root,
            load_result=load_result,
            source_roots=source_roots,
            ignored_paths=ignored_paths,
        ),
        "report": _report_to_json(report),
        "status_context": _build_status_context(load_result),
    }
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(cache_data, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except (OSError, TypeError, ValueError):
        return


def _build_cache_signature(
    project_root: Path,
    load_result: BlueprintLoadResult,
    source_roots: list[str],
    ignored_paths: list[str],
) -> dict[str, Any]:
    """Build the input signature that decides whether a report cache is valid.

    Args:
        project_root: Root directory of the project being verified.
        load_result: Loaded blueprint authority.
        source_roots: Source roots used by the scanner.
        ignored_paths: Ignored path parts used by the scanner.

    Returns:
        JSON-compatible signature for the current authority and source tree.
    """

    return {
        "schema_version": _SCHEMA_VERSION,
        "analyzer_version": _ANALYZER_VERSION,
        "authority_state": load_result.state,
        "authority_revision": _authority_revision(project_root),
        "authority_files": _file_stat_signature(project_root, _authority_paths(project_root, load_result)),
        "source_files": _file_stat_signature(project_root, _source_paths(project_root, source_roots, ignored_paths)),
        "source_roots": list(source_roots),
        "ignored_paths": list(ignored_paths),
    }


def _authority_paths(project_root: Path, load_result: BlueprintLoadResult) -> list[Path]:
    """Return authority files that invalidate cached verification reports.

    Args:
        project_root: Root directory of the project being verified.
        load_result: Loaded authority result.

    Returns:
        Existing authority file paths relevant to the current project state.
    """

    from bpfw.core.authority.sqlite.migration import active_backend
    if active_backend(project_root) == "sqlite":
        return [project_root / ".bpfw" / "manifest.json"]
    candidate_paths: list[Path] = []
    blueprint_path = project_root / ".bpfw" / "blueprint.yaml"
    candidate_paths.append(blueprint_path)
    includes = load_result.data.get("includes")
    if isinstance(includes, list):
        for include_path in includes:
            if isinstance(include_path, str):
                candidate_paths.append(project_root / include_path)
    return sorted(path for path in candidate_paths if path.exists())


def _source_paths(project_root: Path, source_roots: list[str], ignored_paths: list[str]) -> list[Path]:
    """Return source files that invalidate cached verification reports.

    Args:
        project_root: Root directory of the project being verified.
        source_roots: Source roots used by the scanner.
        ignored_paths: Ignored path parts used by the scanner.

    Returns:
        Existing Python source file paths considered by the scanner.
    """

    source_paths: list[Path] = []
    for source_root in source_roots:
        source_root_path = project_root / source_root
        if not source_root_path.exists() or not source_root_path.is_dir():
            continue
        for python_file, _relative_path, _language in iter_source_files(
            project_root, [source_root], ignored_paths
        ):
            source_paths.append(python_file)
    return source_paths


def _is_path_ignored(file_path: Path, ignored_paths: list[str]) -> bool:
    """Return whether a project-relative path is ignored by scanner settings.

    Args:
        file_path: Project-relative path to inspect.
        ignored_paths: Ignored path parts from blueprint settings.

    Returns:
        True when any ignored path part appears in the file path.
    """

    path_parts = file_path.parts
    return any(ignored_path in path_parts for ignored_path in ignored_paths)


def _file_stat_signature(project_root: Path, file_paths: list[Path]) -> list[dict[str, Any]]:
    """Build a stable stat-based signature for file paths.

    Args:
        project_root: Root directory used for relative paths.
        file_paths: File paths to sign.

    Returns:
        List of dictionaries containing path, size, and mtime_ns.
    """

    entries: list[dict[str, Any]] = []
    for file_path in sorted(file_paths):
        try:
            stat_result = file_path.stat()
            relative_path = file_path.relative_to(project_root).as_posix()
        except (FileNotFoundError, OSError, ValueError):
            continue
        entries.append(
            {
                "path": relative_path,
                "size": stat_result.st_size,
                "mtime_ns": stat_result.st_mtime_ns,
            }
        )
    return entries



def _build_status_context(load_result: BlueprintLoadResult) -> dict[str, Any]:
    """Build reusable status rendering data from loaded authority.

    Args:
        load_result: Loaded blueprint authority.

    Returns:
        JSON-compatible status context.
    """

    authority_config = load_result.data.get("authority")
    if not isinstance(authority_config, dict):
        authority_config = {}
    includes = load_result.data.get("includes")
    blocks = load_result.data.get("blocks")
    lifecycle_counts = {
        "active": 0,
        "experimental": 0,
        "legacy": 0,
        "deprecated": 0,
    }
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, dict):
                continue
            status = block.get("status")
            if isinstance(status, str) and status in lifecycle_counts:
                lifecycle_counts[status] += 1
    return {
        "blueprint_path": ".bpfw/blueprint.yaml",
        "authority_config": _json_safe(authority_config),
        "included_shards_count": len(includes) if isinstance(includes, list) else 0,
        "lifecycle_counts": lifecycle_counts,
    }

def _report_to_json(report: VerificationReport) -> dict[str, Any]:
    """Serialize a verification report into JSON-compatible data.

    Args:
        report: Verification report to serialize.

    Returns:
        JSON-compatible report dictionary.
    """

    return {
        "authority_state": report.authority_state,
        "allowed": report.allowed,
        "declared_count": report.declared_count,
        "discovered_count": report.discovered_count,
        "missing_declared_count": report.missing_declared_count,
        "undeclared_count": report.undeclared_count,
        "duplicate_active_purpose_count": report.duplicate_active_purpose_count,
        "duplicate_active_profile_count": report.duplicate_active_profile_count,
        "duplicate_profile_review_count": report.duplicate_profile_review_count,
        "invalid_lifecycle_count": report.invalid_lifecycle_count,
        "incomplete_responsibility_count": report.incomplete_responsibility_count,
        "source_roots": report.source_roots,
        "source_file_counts": report.source_file_counts,
        "discovered_by_language": report.discovered_by_language,
        "logical_component_count": report.logical_component_count,
        "code_component_count": report.code_component_count,
        "findings": [_finding_to_json(finding) for finding in report.findings],
    }


def _report_from_json(data: dict[str, Any]) -> VerificationReport:
    """Restore a verification report from JSON-compatible data.

    Args:
        data: Report dictionary loaded from the cache file.

    Returns:
        Restored verification report.
    """

    findings_data = data.get("findings")
    if not isinstance(findings_data, list):
        raise ValueError("Cached report findings must be a list.")
    return VerificationReport(
        authority_state=str(data.get("authority_state", "invalid")),
        allowed=bool(data.get("allowed", False)),
        findings=[_finding_from_json(item) for item in findings_data if isinstance(item, dict)],
        declared_count=_safe_int(data.get("declared_count")),
        discovered_count=_safe_int(data.get("discovered_count")),
        missing_declared_count=_safe_int(data.get("missing_declared_count")),
        undeclared_count=_safe_int(data.get("undeclared_count")),
        duplicate_active_purpose_count=_safe_int(data.get("duplicate_active_purpose_count")),
        duplicate_active_profile_count=_safe_int(data.get("duplicate_active_profile_count")),
        duplicate_profile_review_count=_safe_int(data.get("duplicate_profile_review_count")),
        invalid_lifecycle_count=_safe_int(data.get("invalid_lifecycle_count")),
        incomplete_responsibility_count=_safe_int(data.get("incomplete_responsibility_count")),
        source_roots=_string_list(data.get("source_roots")),
        source_file_counts={str(key): _safe_int(value) for key, value in dict(data.get("source_file_counts") or {}).items()},
        discovered_by_language={str(key): _safe_int(value) for key, value in dict(data.get("discovered_by_language") or {}).items()},
        logical_component_count=_safe_int(data.get("logical_component_count")),
        code_component_count=_safe_int(data.get("code_component_count")),
    )


def _finding_to_json(finding: Finding) -> dict[str, Any]:
    """Serialize one finding into JSON-compatible data.

    Args:
        finding: Finding to serialize.

    Returns:
        JSON-compatible finding dictionary.
    """

    return {
        "source": finding.source,
        "code": finding.code,
        "severity": finding.severity,
        "message": finding.message,
        "path": finding.path,
        "symbol": finding.symbol,
        "evidence": _json_safe(finding.evidence),
    }


def _finding_from_json(data: dict[str, Any]) -> Finding:
    """Restore one finding from JSON-compatible data.

    Args:
        data: Finding dictionary loaded from cache.

    Returns:
        Restored finding object.
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


def _json_safe(value: Any) -> Any:
    """Return a JSON-safe version of a value.

    Args:
        value: Candidate value that may include tuples, sets, or paths.

    Returns:
        JSON-compatible value.
    """

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)



def _string_list(value: Any) -> list[str]:
    """Return a list of strings.

    Args:
        value: Candidate list value.

    Returns:
        String list with blank items removed.
    """

    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]

def _safe_int(value: Any) -> int:
    """Return an integer value or zero when conversion is unsafe.

    Args:
        value: Candidate integer value.

    Returns:
        Integer value or zero.
    """

    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


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


def _authority_revision(project_root: Path) -> int | None:
    """Avoid stale verification caches when SQLite updates while WAL is open."""
    from bpfw.core.authority.sqlite.migration import active_backend
    if active_backend(project_root) == "sqlite":
        from bpfw.core.authority.sqlite.store import SqliteAuthorityStore
        return SqliteAuthorityStore(project_root).revision()
    return None
