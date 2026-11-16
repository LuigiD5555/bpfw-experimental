"""Idempotent SQLite authority-outbox projection into the BPFW semantic ledger.

The write transaction commits authority and outbox together; the projector
runs after commit, and retries retained events if interrupted. The event ID is
stable across retries, so a repeated projection does not duplicate entries.
"""
from __future__ import annotations

import json
from pathlib import Path

from .migration import active_backend
from .store import SqliteAuthorityStore, now


def project_outbox(project_root: Path, *, limit: int = 100) -> dict[str, int]:
    if active_backend(project_root) != 'sqlite':
        return {'processed': 0, 'pending': 0}
    from bpfw.core.history.ledger import HistoryLedger
    store = SqliteAuthorityStore(project_root)
    ledger = HistoryLedger(project_root)
    git_context = ledger.git_context()
    processed = 0
    with store.connect() as conn:
        queued = conn.execute("""SELECT event_id,operation_id,event_type,payload_json,created_at
                                FROM outbox_events WHERE published_at IS NULL
                                ORDER BY created_at,event_id LIMIT ?""", (limit,)).fetchall()
    for row in queued:
        with store.connect() as conn:
            op = conn.execute('SELECT * FROM operation_log WHERE operation_id=?', (row['operation_id'],)).fetchone()
            deltas = conn.execute('SELECT * FROM operation_deltas WHERE operation_id=? ORDER BY seq', (row['operation_id'],)).fetchall()
        if op is None:
            raise RuntimeError('Orphaned authority outbox operation')
        with ledger.batch():
            for delta in deltas:
                old = json.loads(delta['before_json']) if delta['before_json'] is not None else None
                new = json.loads(delta['after_json']) if delta['after_json'] is not None else None
                entity = new if isinstance(new, dict) else old if isinstance(old, dict) else {}
                is_block = delta['kind'].startswith('block.')
                if not is_block:
                    event_type = 'SQLITE_AUTHORITY_CHANGED'
                elif old is None:
                    event_type = 'BLOCK_CREATED'
                elif new is None:
                    event_type = 'BLOCK_REMOVED'
                elif old.get('id') != new.get('id'):
                    event_type = 'BLOCK_RENAMED'
                elif old.get('intent') != new.get('intent') or old.get('purpose') != new.get('purpose'):
                    event_type = 'INTENT_MODIFIED'
                elif old.get('code') != new.get('code') or old.get('artifacts') != new.get('artifacts'):
                    event_type = 'ARTIFACT_BINDING_MODIFIED'
                elif old.get('connections') != new.get('connections'):
                    event_type = 'FLOW_MODIFIED'
                elif old.get('invariants') != new.get('invariants'):
                    event_type = 'INVARIANTS_MODIFIED'
                else:
                    event_type = 'BLOCK_METADATA_MODIFIED'
                changed = sorted(set(old or {}) ^ set(new or {})) if isinstance(old, dict) and isinstance(new, dict) else []
                if isinstance(old, dict) and isinstance(new, dict):
                    changed = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
                payload = {
                    'git': git_context,
                    'event_id': f"{row['event_id']}-{delta['seq']}",
                    'timestamp': row['created_at'],
                    'event_type': event_type,
                    'change_set_id': row['operation_id'],
                    'entity': {'uid': entity.get('uid') or delta['entity_uid'],
                               'type': 'blueprint_block' if is_block else 'authority_section',
                               'id_at_event': entity.get('id') or delta['entity_uid']},
                    'change': {'operation': delta['kind'], 'fields': changed,
                               'before': ledger.store_object(old) if old is not None else None,
                               'after': ledger.store_object(new) if new is not None else None},
                    'reason': {'summary': op['reason']},
                    'provenance': {'trigger': 'sqlite.outbox', 'actor': op['actor']},
                    'location': {'path': entity.get('code', {}).get('path') if isinstance(entity.get('code'), dict) else '.bpfw/authority.sqlite'},
                    'decision': {'status': 'accepted'},
                }
                ledger.append(payload)
        # Marks published only after durable ledger events are indexed.
        with store.connect(write=True) as conn:
            conn.execute('UPDATE outbox_events SET published_at=? WHERE event_id=? AND published_at IS NULL',
                         (now(), row['event_id']))
        processed += 1
    with store.connect() as conn:
        pending = conn.execute('SELECT COUNT(*) FROM outbox_events WHERE published_at IS NULL').fetchone()[0]
    return {'processed': processed, 'pending': pending}
