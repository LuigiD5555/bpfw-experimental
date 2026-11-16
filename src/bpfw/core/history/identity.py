"""Stable identity helpers for historical lineage."""
from __future__ import annotations
import uuid
from typing import Any

_PREFIX = {"block": "bp", "artifact": "art", "invariant": "inv", "connection": "rel"}

def _new(kind: str) -> str:
    return f"{_PREFIX[kind]}_{uuid.uuid4().hex}"

def ensure_authority_uids(blueprint_data: dict[str, Any]) -> bool:
    changed = False
    blocks = blueprint_data.get("blocks")
    if not isinstance(blocks, list):
        return False
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if not isinstance(block.get("uid"), str) or not block.get("uid", "").strip():
            block["uid"] = _new("block"); changed = True
        code = block.get("code")
        if isinstance(code, dict) and code.get("path") and (not isinstance(code.get("uid"), str) or not code.get("uid", "").strip()):
            code["uid"] = _new("artifact"); changed = True
        for key, kind in (("artifacts", "artifact"), ("invariants", "invariant"), ("connections", "connection")):
            values = block.get(key)
            if not isinstance(values, list):
                continue
            for item in values:
                if isinstance(item, dict) and (not isinstance(item.get("uid"), str) or not item.get("uid", "").strip()):
                    item["uid"] = _new(kind); changed = True
    project_invariants = blueprint_data.get("invariants")
    if isinstance(project_invariants, list):
        for item in project_invariants:
            if isinstance(item, dict) and (not isinstance(item.get("uid"), str) or not item.get("uid", "").strip()):
                item["uid"] = _new("invariant"); changed = True
    return changed
