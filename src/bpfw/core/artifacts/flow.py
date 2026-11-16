"""High-confidence discovery of external artifacts that govern runtime flow."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any

_FLOW_SUFFIXES = {".md", ".prompt", ".txt", ".yaml", ".yml", ".json", ".toml", ".tmpl", ".tpl"}
_EMBED = re.compile(r"^\s*//go:embed\s+(.+?)\s*$", re.M)
_STRING_PATH = re.compile(r'["`]([^"`]+\.(?:md|prompt|txt|ya?ml|json|toml|tmpl|tpl))["`]', re.I)


def discover_flow_artifact_candidates(project_root: Path, blueprint_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return high-confidence prompt/config/spec references not bound to artifacts."""
    bound = set()
    for block in blueprint_data.get("blocks", []) if isinstance(blueprint_data.get("blocks"), list) else []:
        if not isinstance(block, dict):
            continue
        for art in block.get("artifacts", []) if isinstance(block.get("artifacts"), list) else []:
            if isinstance(art, dict) and isinstance(art.get("path"), str):
                bound.add(art["path"].replace("\\", "/"))
    candidates: dict[str, dict[str, Any]] = {}
    for go_file in project_root.rglob("*.go"):
        if ".bpfw" in go_file.parts or ".git" in go_file.parts or "vendor" in go_file.parts:
            continue
        try:
            text = go_file.read_text(encoding="utf-8")
            source = go_file.relative_to(project_root).as_posix()
        except (OSError, ValueError):
            continue
        paths = []
        for match in _EMBED.finditer(text):
            paths.extend(part for part in match.group(1).split() if not any(ch in part for ch in "*?[]"))
        paths.extend(match.group(1) for match in _STRING_PATH.finditer(text))
        for raw in paths:
            target = (go_file.parent / raw).resolve()
            try:
                rel = target.relative_to(project_root.resolve()).as_posix()
            except ValueError:
                continue
            if Path(rel).suffix.lower() not in _FLOW_SUFFIXES or not target.is_file() or rel in bound:
                continue
            candidates[rel] = {"path": rel, "referenced_by": source, "confidence": "high"}
    return sorted(candidates.values(), key=lambda item: item["path"])
