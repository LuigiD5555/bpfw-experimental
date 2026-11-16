"""Rewrite an existing BPFW history ledger in the compact format, without losing events.

WHY: ledgers written by older BPFW versions keep every batch as plain JSON, repeat the same content objects in
every batch that references them, store loose objects and artifact-state.json indented, and keep an index
whose object payloads are uncompressed and never vacuumed. This module previews and, on request, applies:

* every events file rewritten as compact gzip (``.json.gz``), each content object kept only in the first
  batch that contains it (later batches reference it by digest, as new batches already do);
* loose content objects and artifact-state.json rewritten as compact JSON;
* the index rebuilt from the archives (objects stored compressed) and vacuumed.

No event is dropped. Each new archive is written atomically before its original is removed.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

from bpfw.core.atomic_io import atomic_write_bytes, atomic_write_text
from bpfw.core.history.ledger import (
    _BATCH_SCHEMA,
    _GZIP_SUFFIX,
    _INLINE_CLOSURE_LIMIT,
    HistoryLedger,
    _canonical,
    _compact_json,
    _gzip_json,
    _history_files,
    _read_history_file,
)


def _compact_event_impact(event: dict[str, Any], objects_out: dict[str, Any]) -> bool:
    """Replace a long inline impact closure with a shared component reference (same form new events use)."""
    impact = event.get("impact_at_event")
    if not isinstance(impact, dict) or not isinstance(impact.get("closure"), list):
        return False
    closure = impact["closure"]
    entity = event.get("entity") if isinstance(event.get("entity"), dict) else {}
    anchor = entity.get("owner_id") or entity.get("id_at_event")
    if len(closure) <= _INLINE_CLOSURE_LIMIT or not anchor:
        return False
    component = sorted({str(anchor), *(str(member) for member in closure)})
    checksum = hashlib.sha256(_canonical(component)).hexdigest()
    objects_out[checksum] = component
    event["impact_at_event"] = {"direct": impact.get("direct", []), "closure_size": len(closure),
                                "component": f"sha256:{checksum}"}
    return True


def _tree_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file()) if root.exists() else 0


def history_sizes(project_root: Path) -> dict[str, int]:
    """Byte size of each history component."""
    ledger = HistoryLedger(project_root)
    state = ledger.root / "artifact-state.json"
    return {
        "events_bytes": _tree_bytes(ledger.events_root),
        "objects_bytes": _tree_bytes(ledger.root / "objects"),
        "index_bytes": sum(path.stat().st_size for path in ledger.root.glob("index.sqlite*") if path.is_file()),
        "artifact_state_bytes": state.stat().st_size if state.exists() else 0,
    }


def plan_history_compaction(project_root: Path) -> dict[str, Any]:
    """Describe the ledger without writing."""
    ledger = HistoryLedger(project_root)
    files = _history_files(ledger.events_root)
    plain = [path for path in files if not path.name.endswith(_GZIP_SUFFIX)]
    sizes = history_sizes(project_root)
    return {**sizes, "total_bytes": sum(sizes.values()), "event_files": len(files),
            "plain_event_files": len(plain)}


def apply_history_compaction(project_root: Path) -> dict[str, Any]:
    """Rewrite archives, loose objects and state compactly, then rebuild and vacuum the index."""
    ledger = HistoryLedger(project_root)
    before = plan_history_compaction(project_root)
    seen_objects: set[str] = set()
    rewritten = dropped_duplicate_objects = compacted_impacts = 0
    for path in _history_files(ledger.events_root):
        payload = _read_history_file(path)
        if isinstance(payload, dict) and payload.get("schema") == _BATCH_SCHEMA:
            objects = dict(payload.get("objects") or {})
            for event in payload.get("events") or []:
                if isinstance(event, dict) and _compact_event_impact(event, objects):
                    compacted_impacts += 1
            kept = {checksum: value for checksum, value in objects.items() if checksum not in seen_objects}
            dropped_duplicate_objects += len(objects) - len(kept)
            seen_objects.update(kept)
            payload = {**payload, "objects": kept}
        elif isinstance(payload, dict):
            loose: dict[str, Any] = {}
            if _compact_event_impact(payload, loose):
                compacted_impacts += 1
                for value in loose.values():
                    ledger.store_object(value)
        target = path if path.name.endswith(_GZIP_SUFFIX) else path.with_name(path.name[: -len(".json")] + _GZIP_SUFFIX)
        atomic_write_bytes(target, _gzip_json(payload))
        if target != path:
            path.unlink()
        rewritten += 1
    objects_root = ledger.objects_root
    loose = sorted(objects_root.rglob("*.json")) if objects_root.exists() else []
    for path in loose:
        atomic_write_text(path, _compact_json(_read_history_file(path)) + "\n")
    state = ledger.root / "artifact-state.json"
    if state.exists():
        atomic_write_text(state, _compact_json(_read_history_file(state)) + "\n")
    for stale in ledger.root.glob("index.sqlite*"):
        stale.unlink()
    ledger.rebuild_index()
    connection = sqlite3.connect(ledger.index_path)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("VACUUM")
    finally:
        connection.close()
    after = plan_history_compaction(project_root)
    return {"applied": True, "rewritten_event_files": rewritten, "compacted_loose_objects": len(loose),
            "dropped_duplicate_objects": dropped_duplicate_objects, "compacted_impact_closures": compacted_impacts,
            "total_bytes_before": before["total_bytes"], "total_bytes_after": after["total_bytes"]}
