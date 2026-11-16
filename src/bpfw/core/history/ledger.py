"""Append-only semantic history for BPFW authority and physical artifacts."""
from __future__ import annotations

from contextlib import closing, contextmanager

import hashlib
import json
import os
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from bpfw.core.atomic_io import atomic_write_text
from bpfw.core.history.identity import ensure_authority_uids
from bpfw.core.artifacts.resolver import ArtifactResolver, block_artifacts

_HISTORY = Path(".bpfw/history")
_SECRET_KEYS = {"password", "passwd", "secret", "token", "api_key", "apikey", "access_key", "private_key", "credential", "credentials"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _redact(value: Any, key: str | None = None) -> Any:
    if key and any(secret in key.casefold() for secret in _SECRET_KEYS):
        encoded = json.dumps(value, sort_keys=True, default=str).encode()
        return {"redacted": True, "sha256": hashlib.sha256(encoded).hexdigest()}
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(_redact(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def read_authority_snapshot(project_root: Path) -> dict[str, Any]:
    from bpfw.core.authority.sqlite.migration import active_backend
    if active_backend(project_root) == "sqlite":
        from bpfw.core.authority.sqlite.store import SqliteAuthorityStore
        return SqliteAuthorityStore(project_root).load_document()
    index = project_root / ".bpfw" / "blueprint.yaml"
    if not index.is_file():
        return {}
    try:
        raw = yaml.safe_load(index.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    if raw.get("authority", {}).get("layout") == "sharded" and isinstance(raw.get("includes"), list):
        blocks = []
        for include in raw["includes"]:
            if not isinstance(include, str): continue
            shard = project_root / include
            try:
                payload = yaml.safe_load(shard.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            if isinstance(payload, dict) and isinstance(payload.get("blocks"), list):
                blocks.extend(item for item in payload["blocks"] if isinstance(item, dict))
        raw["blocks"] = blocks
    return raw


class HistoryLedger:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.root = self.project_root / _HISTORY
        self.events_root = self.root / "events"
        self.objects_root = self.root / "objects" / "sha256"
        self.index_path = self.root / "index.sqlite"
        self._pending_events: list[dict[str, Any]] | None = None
        self._pending_objects: dict[str, Any] = {}

    @contextmanager
    def batch(self):
        """Durably archive a set of events and content objects with one index commit."""
        if self._pending_events is not None:
            raise RuntimeError("Nested history batches are not supported")
        self._pending_events = []
        self._pending_objects = {}
        try:
            yield self
            if self._pending_events or self._pending_objects:
                timestamp = self._pending_events[0]["timestamp"] if self._pending_events else _now()
                moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                path = self.events_root / f"{moment.year:04d}" / f"{moment.month:02d}" / (_id("batch") + ".json")
                payload = {"schema": "bpfw.history.batch/v1", "events": self._pending_events,
                           "objects": self._pending_objects}
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(path, json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n")
                self._index_events(self._pending_events, self._pending_objects)
        finally:
            self._pending_events = None
            self._pending_objects = {}

    def ensure_baseline(self, snapshot: dict[str, Any] | None = None) -> None:
        """Record the explicit point from which trustworthy semantic history begins."""
        marker = self.root / "baseline.json"
        if marker.exists():
            return
        snapshot = snapshot or read_authority_snapshot(self.project_root)
        payload = {
            "schema": "bpfw.history.baseline/v1",
            "created_at": _now(),
            "authority": self.store_object(snapshot) if snapshot else None,
            "note": "Current authority imported as history baseline; earlier semantic history is unavailable unless backfilled.",
        }
        marker.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(marker, json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        self.append({
            "event_type": "HISTORY_BASELINE_CREATED",
            "entity": {"type": "project", "id_at_event": str(snapshot.get("project", {}).get("id") or self.project_root.name) if isinstance(snapshot, dict) else self.project_root.name},
            "change": {"after": payload.get("authority")},
            "provenance": {"trigger": "history.initialize"},
            "decision": {"status": "accepted"},
        })

    def store_object(self, value: Any) -> str:
        data = _canonical(value)
        digest = hashlib.sha256(data).hexdigest()
        if self._pending_events is not None:
            self._pending_objects[digest] = _redact(value)
            return f"sha256:{digest}"
        path = self.objects_root / digest[:2] / f"{digest}.json"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, json.dumps(_redact(value), ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n")
        return f"sha256:{digest}"

    def read_object(self, reference: str) -> Any:
        """Read a content reference from either historical files or indexed batches."""
        prefix, separator, checksum = reference.partition(":")
        if prefix != "sha256" or not separator or len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum):
            raise ValueError("Invalid history object reference")
        path = self.objects_root / checksum[:2] / f"{checksum}.json"
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        if not self.index_path.exists():
            self.rebuild_index()
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT payload FROM object_blobs WHERE digest=?", (checksum,)).fetchone()
        if row is None:
            raise KeyError(reference)
        return json.loads(row[0])

    def git_context(self) -> dict[str, Any]:
        def run(*args: str) -> str | None:
            try:
                return subprocess.run(["git", *args], cwd=self.project_root, text=True, capture_output=True, check=True, timeout=2).stdout.strip() or None
            except Exception:
                return None
        return {
            "branch": run("branch", "--show-current"),
            "head_commit": run("rev-parse", "HEAD"),
            "worktree_dirty": bool(run("status", "--porcelain")),
        }

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        event = dict(event)
        event.setdefault("schema", "bpfw.history.event/v1")
        event.setdefault("event_id", _id("evt"))
        event.setdefault("timestamp", _now())
        if "git" not in event:
            event["git"] = self.git_context()
        if self._pending_events is not None:
            self._pending_events.append(_redact(event))
            return event
        dt = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
        path = self.events_root / f"{dt.year:04d}" / f"{dt.month:02d}" / f"{event['event_id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(_redact(event), ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n")
        self._index_event(_redact(event))
        return event

    def _connect(self) -> sqlite3.Connection:
        self.root.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.index_path)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY, timestamp TEXT, event_type TEXT, entity_uid TEXT, entity_id TEXT, entity_type TEXT, owner_uid TEXT, owner_id TEXT, path TEXT, symbol TEXT, reason TEXT, payload TEXT)")
        columns = {row[1] for row in con.execute("PRAGMA table_info(events)").fetchall()}
        if "owner_id" not in columns:
            con.execute("DROP TABLE events")
            con.execute("CREATE TABLE events(event_id TEXT PRIMARY KEY, timestamp TEXT, event_type TEXT, entity_uid TEXT, entity_id TEXT, entity_type TEXT, owner_uid TEXT, owner_id TEXT, path TEXT, symbol TEXT, reason TEXT, payload TEXT)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_entity ON events(entity_uid, entity_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_owner ON events(owner_uid, owner_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_path ON events(path)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")
        con.execute("CREATE TABLE IF NOT EXISTS object_blobs(digest TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        return con

    def _index_event(self, event: dict[str, Any]) -> None:
        self._index_events([event], {})

    @staticmethod
    def _event_row(event: dict[str, Any]) -> tuple:
        entity = event.get("entity") if isinstance(event.get("entity"), dict) else {}
        location = event.get("location") if isinstance(event.get("location"), dict) else {}
        reason = event.get("reason")
        if isinstance(reason, dict): reason = reason.get("summary") or reason.get("details")
        return (event.get("event_id"), event.get("timestamp"), event.get("event_type"), entity.get("uid"),
                entity.get("id_at_event") or entity.get("id"), entity.get("type"), entity.get("owner_uid"),
                entity.get("owner_id"), location.get("path"), location.get("symbol"),
                reason if isinstance(reason, str) else None, json.dumps(event, ensure_ascii=False, default=str))

    def _index_events(self, events: list[dict[str, Any]], objects: dict[str, Any], *, replace: bool = False) -> None:
        with closing(self._connect()) as connection, connection:
            if replace:
                connection.execute("DELETE FROM events")
                connection.execute("DELETE FROM object_blobs")
            connection.executemany("INSERT OR REPLACE INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                                   (self._event_row(event) for event in events))
            connection.executemany("INSERT OR IGNORE INTO object_blobs VALUES(?,?)",
                                   ((checksum, json.dumps(value, ensure_ascii=False, default=str)) for checksum, value in objects.items()))

    def rebuild_index(self) -> None:
        events: list[dict[str, Any]] = []
        objects: dict[str, Any] = {}
        for path in sorted(self.events_root.rglob("*.json")) if self.events_root.exists() else []:
            try: event = json.loads(path.read_text(encoding="utf-8"))
            except Exception: continue
            if not isinstance(event, dict):
                continue
            if event.get("schema") == "bpfw.history.batch/v1":
                events.extend(item for item in event.get("events", []) if isinstance(item, dict) and item.get("event_id"))
                objects.update(event.get("objects", {}))
            elif event.get("event_id"):
                events.append(event)
        self._index_events(events, objects, replace=True)

    def query(self, target: str | None = None, *, event_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        from bpfw.core.authority.sqlite.history import project_outbox
        project_outbox(self.project_root)
        if not self.index_path.exists(): self.rebuild_index()
        sql = "SELECT payload FROM events WHERE 1=1"; params: list[Any] = []
        if target:
            sql += " AND (entity_uid=? OR entity_id=? OR owner_uid=? OR owner_id=? OR path=? OR symbol=?)"
            params.extend([target, target, target, target, target, target])
        if event_type:
            sql += " AND event_type=?"; params.append(event_type)
        sql += " ORDER BY timestamp DESC LIMIT ?"; params.append(limit)
        try:
            with self._connect() as con: rows = con.execute(sql, params).fetchall()
        except sqlite3.DatabaseError:
            self.rebuild_index()
            with self._connect() as con: rows = con.execute(sql, params).fetchall()
        return [json.loads(row[0]) for row in rows]

    def search(self, text: str, *, limit: int = 100) -> list[dict[str, Any]]:
        """Full payload search for reasons, aliases, paths, prompt headings, and evidence."""
        from bpfw.core.authority.sqlite.history import project_outbox
        project_outbox(self.project_root)
        if not self.index_path.exists():
            self.rebuild_index()
        with self._connect() as con:
            rows = con.execute(
                "SELECT payload FROM events WHERE payload LIKE ? ORDER BY timestamp DESC LIMIT ?",
                (f"%{text}%", limit),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def why(self, target: str) -> list[dict[str, Any]]:
        events = self.query(target, limit=200)
        preferred = [e for e in events if e.get("event_type") in {"INTENT_ACCEPTED", "INTENT_MODIFIED", "INVARIANT_MODIFIED", "INVARIANT_CREATED", "CHANGE_ACCEPTED"} and e.get("reason")]
        return preferred or [e for e in events if e.get("reason")][:20]


def _block_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {}
    for block in snapshot.get("blocks", []) if isinstance(snapshot.get("blocks"), list) else []:
        if isinstance(block, dict):
            key = block.get("uid") if isinstance(block.get("uid"), str) else block.get("id")
            if isinstance(key, str): result[key] = block
    return result


def _changed_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    keys = sorted(set(before) | set(after))
    return [key for key in keys if _canonical(before.get(key)) != _canonical(after.get(key))]


def _impact_graph(snapshot: dict[str, Any]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Build the authority connection graph once for a history capture."""
    blocks = [block for block in snapshot.get("blocks", []) if isinstance(block, dict)] if isinstance(snapshot.get("blocks"), list) else []
    outgoing: dict[str, set[str]] = {}; reverse: dict[str, set[str]] = {}
    for block in blocks:
        block_id = block.get("id")
        if not isinstance(block_id, str): continue
        for connection in block.get("connections", []) if isinstance(block.get("connections"), list) else []:
            if isinstance(connection, dict) and isinstance(connection.get("target"), str):
                target = connection["target"]
                outgoing.setdefault(block_id, set()).add(target)
                reverse.setdefault(target, set()).add(block_id)
    return outgoing, reverse


def _impact(snapshot: dict[str, Any], block_id: str, *, graph: tuple[dict[str, set[str]], dict[str, set[str]]] | None = None) -> dict[str, Any]:
    outgoing, reverse = graph if graph is not None else _impact_graph(snapshot)
    direct = sorted(outgoing.get(block_id, set()) | reverse.get(block_id, set()))
    seen = {block_id}; queue = list(direct); closure = []
    while queue:
        cur = queue.pop(0)
        if cur in seen: continue
        seen.add(cur); closure.append(cur)
        queue.extend(sorted((outgoing.get(cur, set()) | reverse.get(cur, set())) - seen))
    return {"direct": direct, "closure": closure}


def _natural_child_key(item: dict[str, Any], child_type: str) -> str:
    if isinstance(item.get("uid"), str) and item.get("uid"):
        return "uid:" + item["uid"]
    if isinstance(item.get("id"), str) and item.get("id"):
        return "id:" + item["id"]
    if child_type == "artifact":
        return "artifact:" + ":".join(str(item.get(k) or "") for k in ("type", "path", "symbol", "kind"))
    if child_type == "connection":
        return "connection:" + ":".join(str(item.get(k) or "") for k in ("relationship", "target"))
    return child_type + ":" + hashlib.sha256(_canonical(item)).hexdigest()


def _semantic_child_key(item: dict[str, Any], child_type: str) -> str:
    if child_type == "artifact":
        return "artifact:" + ":".join(str(item.get(k) or "") for k in ("type", "path", "symbol", "kind"))
    if child_type == "connection":
        return "connection:" + ":".join(str(item.get(k) or "") for k in ("relationship", "target"))
    if child_type == "invariant":
        return "invariant:" + str(item.get("id") or item.get("description") or "")
    return child_type + ":" + hashlib.sha256(_canonical({k: v for k, v in item.items() if k != "uid"})).hexdigest()


def _pair_children(before_values: Any, after_values: Any, child_type: str) -> list[tuple[dict[str, Any] | None, dict[str, Any] | None]]:
    before_list = [x for x in before_values if isinstance(x, dict)] if isinstance(before_values, list) else []
    after_list = [x for x in after_values if isinstance(x, dict)] if isinstance(after_values, list) else []
    by_uid = {x.get("uid"): x for x in before_list if isinstance(x.get("uid"), str)}
    by_id = {x.get("id"): x for x in before_list if isinstance(x.get("id"), str)}
    by_natural = {_semantic_child_key(x, child_type): x for x in before_list}
    used: set[int] = set(); pairs = []
    for new in after_list:
        old = by_uid.get(new.get("uid")) if isinstance(new.get("uid"), str) else None
        if old is None and isinstance(new.get("id"), str): old = by_id.get(new.get("id"))
        if old is None: old = by_natural.get(_semantic_child_key(new, child_type))
        if old is not None: used.add(id(old))
        pairs.append((old, new))
    for old in before_list:
        if id(old) not in used: pairs.append((old, None))
    return pairs


def _append_child_events(
    ledger: HistoryLedger, change_set: str, owner: dict[str, Any], old: dict[str, Any] | None, new: dict[str, Any] | None,
    *, trigger: str, reason: str | None, snapshot: dict[str, Any], events: list[dict[str, Any]],
) -> None:
    owner_id = str((new or old or {}).get("id") or "")
    owner_uid = (new or old or {}).get("uid")
    specs = [
        ("artifacts", "artifact", "ARTIFACT_BOUND", "ARTIFACT_UNBOUND", "ARTIFACT_METADATA_MODIFIED"),
        ("invariants", "invariant", "INVARIANT_CREATED", "INVARIANT_REMOVED", "INVARIANT_MODIFIED"),
        ("connections", "connection", "FLOW_EDGE_ADDED", "FLOW_EDGE_REMOVED", "FLOW_EDGE_MODIFIED"),
    ]
    for field, child_type, created_type, removed_type, modified_type in specs:
        for child_old, child_new in _pair_children(old.get(field, []) if old else [], new.get(field, []) if new else [], child_type):
            if child_old is not None and child_new is not None:
                changed = [x for x in _changed_fields(child_old, child_new) if x != "uid"]
                if not changed: continue
                etype = modified_type
            elif child_old is None:
                changed = list((child_new or {}).keys()); etype = created_type
            else:
                changed = list((child_old or {}).keys()); etype = removed_type
            child = child_new or child_old or {}
            child_id = child.get("id") or child.get("symbol") or child.get("path") or child.get("target") or _natural_child_key(child, child_type)
            location = {"path": child.get("path"), "symbol": child.get("symbol")} if child_type == "artifact" else {"path": ".bpfw/blueprint.yaml"}
            events.append(ledger.append({
                "change_set_id": change_set, "event_type": etype,
                "entity": {"uid": child.get("uid"), "type": child_type, "id_at_event": child_id, "owner_uid": owner_uid, "owner_id": owner_id},
                "change": {"operation": "create" if child_old is None else "remove" if child_new is None else "modify", "fields": changed,
                           "before": ledger.store_object(child_old) if child_old is not None else None,
                           "after": ledger.store_object(child_new) if child_new is not None else None},
                "reason": {"summary": reason} if reason else None,
                "provenance": {"trigger": trigger}, "location": location,
                "impact_at_event": _impact(snapshot, owner_id) if owner_id else {},
                "decision": {"status": "accepted" if reason else "observed"},
            }))


def capture_authority_change(project_root: Path, before: dict[str, Any], after: dict[str, Any], *, trigger: str, reason: str | None = None) -> list[dict[str, Any]]:
    if not after:
        return []
    ledger = HistoryLedger(project_root)
    ledger.ensure_baseline(before or after)
    change_set = _id("chg")
    before_blocks = [b for b in before.get("blocks", []) if isinstance(b, dict)] if isinstance(before.get("blocks"), list) else []
    after_blocks = [b for b in after.get("blocks", []) if isinstance(b, dict)] if isinstance(after.get("blocks"), list) else []
    before_uid = {b.get("uid"): b for b in before_blocks if isinstance(b.get("uid"), str)}
    before_id = {b.get("id"): b for b in before_blocks if isinstance(b.get("id"), str)}
    used_before: set[int] = set()
    pairs: list[tuple[dict[str, Any] | None, dict[str, Any] | None]] = []
    for new in after_blocks:
        old = before_uid.get(new.get("uid")) if isinstance(new.get("uid"), str) else None
        if old is None and isinstance(new.get("id"), str):
            old = before_id.get(new.get("id"))
        if old is not None:
            used_before.add(id(old))
        pairs.append((old, new))
    for old in before_blocks:
        if id(old) not in used_before:
            pairs.append((old, None))

    events = []
    for old, new in pairs:
        if old is None:
            etype, changed = "BLOCK_CREATED", list(new.keys())
        elif new is None:
            etype, changed = "BLOCK_REMOVED", list(old.keys())
        else:
            changed = _changed_fields(old, new)
            # UID assignment is lineage initialization, not a semantic modification.
            semantic_changed = [field for field in changed if field != "uid"]
            changed = semantic_changed
            if any(field in changed for field in ("intent", "purpose")):
                etype = "INTENT_MODIFIED"
            elif "invariants" in changed:
                etype = "INVARIANTS_MODIFIED"
            elif "artifacts" in changed or "code" in changed:
                etype = "ARTIFACT_BINDING_MODIFIED"
            elif "connections" in changed:
                etype = "FLOW_MODIFIED"
            elif "id" in changed:
                etype = "BLOCK_RENAMED"
            else:
                etype = "BLOCK_METADATA_MODIFIED"
        entity = new or old or {}
        bid = str(entity.get("id") or "")
        _append_child_events(ledger, change_set, entity, old, new, trigger=trigger, reason=reason, snapshot=after or before, events=events)
        if old is not None and new is not None and not changed:
            continue
        event = {
            "change_set_id": change_set, "event_type": etype,
            "entity": {"uid": entity.get("uid"), "type": "blueprint_block", "id_at_event": entity.get("id")},
            "change": {"operation": "create" if old is None else "remove" if new is None else "modify", "fields": changed,
                       "before": ledger.store_object(old) if old is not None else None, "after": ledger.store_object(new) if new is not None else None},
            "reason": {"summary": reason} if reason else None,
            "provenance": {"trigger": trigger},
            "location": {"path": ".bpfw/blueprint.yaml"},
            "impact_at_event": _impact(after or before, bid) if bid else {},
            "decision": {"status": "accepted" if reason else "observed"},
        }
        events.append(ledger.append(event))
    return events


def _artifact_state_path(project_root: Path) -> Path:
    return project_root / _HISTORY / "artifact-state.json"


def capture_artifact_state(project_root: Path, blueprint_data: dict[str, Any], *, trigger: str = "verify") -> list[dict[str, Any]]:
    ledger = HistoryLedger(project_root); ledger.ensure_baseline(blueprint_data); resolver = ArtifactResolver(project_root)
    path = _artifact_state_path(project_root)
    try: previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception: previous = {}
    current: dict[str, Any] = {}; events = []; change_set = _id("chg")
    git_context = ledger.git_context()
    impact_graph = _impact_graph(blueprint_data)
    impact_by_block: dict[str, dict[str, Any]] = {}
    with ledger.batch():
        for block in blueprint_data.get("blocks", []) if isinstance(blueprint_data.get("blocks"), list) else []:
            if not isinstance(block, dict): continue
            block_id = block.get("id"); block_uid = block.get("uid")
            for idx, art in enumerate(block_artifacts(block)):
                resolved = resolver.resolve(art)
                key = str(art.get("uid") or f"{block_uid or block_id}:{art.get('id') or idx}:{art.get('path')}:{art.get('symbol')}")
                state = {
                    "block_id": block_id, "block_uid": block_uid, "artifact_uid": art.get("uid"), "artifact_id": art.get("id") or resolved.artifact_id,
                    "type": resolved.type, "path": resolved.path, "symbol": resolved.symbol, "kind": resolved.kind,
                    "start_line": resolved.start_line, "end_line": resolved.end_line, "content_hash": resolved.content_hash,
                    "structural_hash": resolved.structural_hash, "resolution": resolved.resolution, "detected": resolved.detected,
                }
                current[key] = state; old = previous.get(key)
                if old is None:
                    etype = "ARTIFACT_BASELINE"
                elif old == state:
                    continue
                elif old.get("content_hash") == state.get("content_hash") and (old.get("start_line"), old.get("end_line")) != (state.get("start_line"), state.get("end_line")):
                    etype = "ARTIFACT_LOCATION_DRIFT"
                elif state.get("type") == "prompt":
                    if old.get("detected", {}).get("variables") != state.get("detected", {}).get("variables"): etype = "PROMPT_VARIABLE_DRIFT"
                    else: etype = "PROMPT_TEXT_DRIFT"
                elif state.get("type") in {"config", "configuration"}: etype = "CONFIG_VALUE_DRIFT"
                else: etype = "ARTIFACT_CONTENT_DRIFT"
                if block_id and str(block_id) not in impact_by_block:
                    impact_by_block[str(block_id)] = _impact(blueprint_data, str(block_id), graph=impact_graph)
                events.append(ledger.append({
                    "git": git_context,
                    "change_set_id": change_set, "event_type": etype,
                    "entity": {"uid": art.get("uid"), "type": "artifact", "id_at_event": art.get("id") or resolved.artifact_id, "owner_uid": block_uid, "owner_id": block_id},
                    "change": {"before": ledger.store_object(old) if old else None, "after": ledger.store_object(state)},
                    "provenance": {"trigger": trigger},
                    "location": {"path": resolved.path, "symbol": resolved.symbol, "start_line": resolved.start_line, "end_line": resolved.end_line},
                    "impact_at_event": impact_by_block.get(str(block_id), {}),
                    "decision": {"status": "observed"},
                }))
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(current, sort_keys=True, indent=2) + "\n")
    return events
