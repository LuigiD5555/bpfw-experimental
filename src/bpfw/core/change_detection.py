"""Lightweight before/after file snapshots for change-gate impact analysis."""
from __future__ import annotations
import hashlib
from pathlib import Path

_IGNORED_DIRS = {".git", ".bpfw", "__pycache__", ".pytest_cache", ".venv", "venv", "node_modules"}

def snapshot_project(project_root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in project_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(project_root)
        if any(part in _IGNORED_DIRS for part in relative.parts):
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
        result[relative.as_posix()] = digest
    return result

def changed_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    keys = set(before) | set(after)
    return sorted(path for path in keys if before.get(path) != after.get(path))
