"""Explicit maintenance of the SQLite authority's change records.

WHY: operation_deltas and outbox_events only ever grow. Older BPFW versions stored every change as the whole
block before and after, uncompressed, and the database was never vacuumed. This module previews and, on
request, applies a compaction that:

* drops the change records of old operations that were already projected into the history ledger
  (their outbox event is published), keeping the newest ``keep_operations`` operations intact;
* deletes published outbox rows of those pruned operations;
* re-encodes the change records it keeps in the current compact format (field-level, compressed);
* runs VACUUM to return the freed pages to the file system.

operation_log rows (revision, before/after digests, actor, reason) are always kept as the audit trail.
"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .store import (
    SqliteAuthorityStore,
    decode_delta_payload,
    encode_delta_payload,
    field_level_change,
    PARTIAL_MARKER,
)

DEFAULT_KEEP_OPERATIONS = 20


def _prunable_operations(conn: sqlite3.Connection, keep_operations: int) -> list[str]:
    rows = conn.execute("SELECT operation_id FROM operation_log ORDER BY result_revision DESC").fetchall()
    older = [row[0] for row in rows[max(keep_operations, 0):]]
    if not older:
        return []
    pending = {row[0] for row in conn.execute(
        "SELECT DISTINCT operation_id FROM outbox_events WHERE published_at IS NULL")}
    return [operation for operation in older if operation not in pending]


def plan_compaction(store: SqliteAuthorityStore, *, keep_operations: int = DEFAULT_KEEP_OPERATIONS) -> dict[str, Any]:
    """Describe what compaction would remove, without writing."""

    with store.connect() as conn:
        prunable = _prunable_operations(conn, keep_operations)
        total_deltas, total_bytes = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(LENGTH(before_json)) + SUM(LENGTH(after_json)), 0) FROM operation_deltas"
        ).fetchone()
        prunable_deltas, prunable_bytes = 0, 0
        if prunable:
            marks = ",".join("?" * len(prunable))
            prunable_deltas, prunable_bytes = conn.execute(
                f"SELECT COUNT(*), COALESCE(SUM(LENGTH(before_json)) + SUM(LENGTH(after_json)), 0) "
                f"FROM operation_deltas WHERE operation_id IN ({marks})", prunable).fetchone()
        operations = conn.execute("SELECT COUNT(*) FROM operation_log").fetchone()[0]
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        free_pages = conn.execute("PRAGMA freelist_count").fetchone()[0]
    return {
        "database_bytes": store.path.stat().st_size,
        "operations": operations,
        "keep_operations": keep_operations,
        "prunable_operations": len(prunable),
        "change_records": total_deltas,
        "change_record_bytes": total_bytes,
        "prunable_change_records": prunable_deltas,
        "prunable_change_record_bytes": prunable_bytes,
        "free_bytes_before_vacuum": page_size * free_pages,
    }


def _reencode_kept_deltas(conn: sqlite3.Connection) -> int:
    """Compress every kept record; shrink to field level only where the ledger already holds full objects."""
    reencoded = 0
    pending = {row[0] for row in conn.execute(
        "SELECT DISTINCT operation_id FROM outbox_events WHERE published_at IS NULL")}
    rows = conn.execute("SELECT operation_id, seq, kind, before_json, after_json FROM operation_deltas").fetchall()
    for operation_id, seq, kind, before_raw, after_raw in rows:
        old, new = decode_delta_payload(before_raw), decode_delta_payload(after_raw)
        if (kind == "block.upsert" and operation_id not in pending
                and isinstance(old, dict) and isinstance(new, dict) and not old.get(PARTIAL_MARKER)):
            old, new = field_level_change(old, new)
        before_encoded, after_encoded = encode_delta_payload(old), encode_delta_payload(new)
        if before_encoded != before_raw or after_encoded != after_raw:
            conn.execute("UPDATE operation_deltas SET before_json=?, after_json=? WHERE operation_id=? AND seq=?",
                         (before_encoded, after_encoded, operation_id, seq))
            reencoded += 1
    return reencoded


def apply_compaction(project_root: Path, store: SqliteAuthorityStore, *,
                     keep_operations: int = DEFAULT_KEEP_OPERATIONS) -> dict[str, Any]:
    """Back up, prune, re-encode and vacuum the authority database."""

    bytes_before = store.path.stat().st_size
    backup = project_root / ".bpfw" / "backups" / f"authority-before-compact-{uuid.uuid4().hex}.sqlite"
    store.backup(backup)
    with store.connect(write=True) as conn:
        store._require_unlocked(conn)
        prunable = _prunable_operations(conn, keep_operations)
        removed_deltas = removed_outbox = 0
        if prunable:
            marks = ",".join("?" * len(prunable))
            removed_deltas = conn.execute(
                f"DELETE FROM operation_deltas WHERE operation_id IN ({marks})", prunable).rowcount
            removed_outbox = conn.execute(
                f"DELETE FROM outbox_events WHERE published_at IS NOT NULL AND operation_id IN ({marks})",
                prunable).rowcount
        reencoded = _reencode_kept_deltas(conn)
    vacuum = sqlite3.connect(str(store.path), timeout=10)
    try:
        vacuum.execute("VACUUM")
    finally:
        vacuum.close()
    return {
        "applied": True,
        "backup": str(backup),
        "pruned_operations": len(prunable),
        "removed_change_records": removed_deltas,
        "removed_outbox_events": removed_outbox,
        "reencoded_change_records": reencoded,
        "database_bytes_before": bytes_before,
        "database_bytes_after": store.path.stat().st_size,
    }
