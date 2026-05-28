"""PURPOSE persistent Inspector work cache for reusable metadata sessions
DOMAIN  inspector workflow
"""

import json
import hashlib
import os
from pathlib import Path
from typing import Any

from bpfw.integrations.inspector.base import InspectIssue, InspectLoadResult

_SCHEMA_VERSION = 1
_CACHE_RELATIVE_PATH = Path(".bpfw") / "cache" / "inspector_work_cache.json"
_IGNORED_DIRECTORY_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".locks",
        "cache",
    }
)
_AUTHORITY_SUFFIXES: frozenset[str] = frozenset({".yaml", ".yml", ".toml"})


class InspectorWorkCacheRepository:
    """PURPOSE read and save reusable Inspector metadata work
    DOMAIN  inspector workflow
    """

    def __init__(self, project_root: Path) -> None:
        """PURPOSE set up the cache repository
        DOMAIN  inspector workflow
        """
        self.project_root = project_root.resolve()
        self.cache_path = self.project_root / _CACHE_RELATIVE_PATH

    def load_metadata_session(self, authority_signature: str) -> InspectLoadResult | None:
        """PURPOSE read a cached metadata session when the authority signature matches
        DOMAIN  inspector workflow
        """
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        if data.get("schema_version") != _SCHEMA_VERSION:
            return None
        if data.get("authority_signature") != authority_signature:
            return None
        session_data = data.get("metadata_session")
        if not isinstance(session_data, dict):
            return None
        return _session_from_json(project_root=self.project_root, data=session_data)

    def save_metadata_session(self, authority_signature: str, session: InspectLoadResult) -> None:
        """PURPOSE save a metadata Inspector session
        DOMAIN  inspector workflow
        """
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "authority_signature": authority_signature,
            "metadata_session": _session_to_json(session),
        }
        self.cache_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def invalidate(self) -> None:
        """PURPOSE delete the Inspector work cache if it exists
        DOMAIN  inspector workflow
        """
        try:
            self.cache_path.unlink()
        except FileNotFoundError:
            return
        except OSError:
            return


def build_authority_signature(project_root: Path) -> str:
    """PURPOSE build a stable metadata signature for authority/config files
    DOMAIN  inspector workflow
    """
    resolved_root = project_root.resolve()
    authority_root = resolved_root / "bpfw"
    entries: list[dict[str, Any]] = []
    if authority_root.exists() and authority_root.is_dir():
        ignored_directories = set(_IGNORED_DIRECTORY_NAMES)
        for current_root, directory_names, file_names in os.walk(authority_root):
            directory_names[:] = [name for name in directory_names if name not in ignored_directories]
            for file_name in file_names:
                path = Path(current_root) / file_name
                if path.suffix not in _AUTHORITY_SUFFIXES:
                    continue
                try:
                    stat_result = path.stat()
                except OSError:
                    continue
                entries.append(
                    {
                        "path": path.relative_to(resolved_root).as_posix(),
                        "size": stat_result.st_size,
                        "mtime_ns": stat_result.st_mtime_ns,
                    }
                )
    entries.sort(key=lambda entry: entry["path"])
    encoded = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def invalidate_inspector_work_cache(project_root: Path) -> None:
    """PURPOSE invalidate persisted Inspector work for a project
    DOMAIN  inspector workflow
    """
    InspectorWorkCacheRepository(project_root).invalidate()


def _session_to_json(session: InspectLoadResult) -> dict[str, Any]:
    """PURPOSE convert a metadata inspect session
    DOMAIN  inspector workflow
    """
    return {
        "blueprint_path": _relative_path(session.project_root, session.blueprint_path),
        "blueprint_data": session.blueprint_data,
        "incomplete": session.incomplete,
        "issues": [_issue_to_json(issue) for issue in session.issues],
        "authority_state": session.authority_state,
        "pre_inspection_context_lines": list(session.pre_inspection_context_lines),
        "message": session.message,
        "exit_code": session.exit_code,
    }


def _session_from_json(project_root: Path, data: dict[str, Any]) -> InspectLoadResult | None:
    """PURPOSE restore a metadata inspect session from JSON data
    DOMAIN  inspector workflow
    """
    blueprint_data = data.get("blueprint_data")
    incomplete = data.get("incomplete")
    issues_data = data.get("issues")
    if not isinstance(blueprint_data, dict):
        return None
    if not isinstance(incomplete, list):
        return None
    if not isinstance(issues_data, list):
        return None
    issues: list[InspectIssue] = []
    for issue_data in issues_data:
        if not isinstance(issue_data, dict):
            continue
        issue = _issue_from_json(issue_data)
        if issue is not None:
            issues.append(issue)
    blueprint_path = _path_from_json(project_root=project_root, value=data.get("blueprint_path"))
    return InspectLoadResult(
        project_root=project_root,
        blueprint_path=blueprint_path,
        blueprint_data=blueprint_data,
        incomplete=[item for item in incomplete if isinstance(item, dict)],
        issues=issues,
        authority_state=str(data.get("authority_state", "unknown")),
        pre_inspection_context_lines=[str(line) for line in data.get("pre_inspection_context_lines", []) if line is not None],
        message=data.get("message") if isinstance(data.get("message"), str) else None,
        exit_code=_safe_int(data.get("exit_code")),
    )


def _issue_to_json(issue: InspectIssue) -> dict[str, Any]:
    """PURPOSE convert one inspect issue
    DOMAIN  inspector workflow
    """
    return {
        "issue_type": issue.issue_type,
        "block": issue.block,
        "add_on_accept": issue.add_on_accept,
        "context_lines": list(issue.context_lines),
    }


def _issue_from_json(data: dict[str, Any]) -> InspectIssue | None:
    """PURPOSE restore one inspect issue from JSON data
    DOMAIN  inspector workflow
    """
    block = data.get("block")
    if not isinstance(block, dict):
        return None
    context_lines = data.get("context_lines")
    if not isinstance(context_lines, list):
        context_lines = []
    return InspectIssue(
        issue_type=str(data.get("issue_type", "draft")),
        block=block,
        add_on_accept=bool(data.get("add_on_accept", False)),
        context_lines=[str(line) for line in context_lines],
    )


def _relative_path(project_root: Path, path: Path | None) -> str | None:
    """PURPOSE get a path relative to project root when possible
    DOMAIN  inspector workflow
    """
    if path is None:
        return None
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _path_from_json(project_root: Path, value: Any) -> Path | None:
    """PURPOSE restore an path from JSON data
    DOMAIN  inspector workflow
    """
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return project_root / path


def _safe_int(value: Any) -> int:
    """PURPOSE get a safe integer value
    DOMAIN  inspector workflow
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
