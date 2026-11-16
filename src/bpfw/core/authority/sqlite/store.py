"""SQLite authority v1: explicit raw semantics, normalized edges and durable changes.

All persisted edits go through ``apply_patches`` or ``replace_document``.  The
legacy YAML backend is not written or synchronized by this module.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

SCHEMA_VERSION = 1
CHILD_KEYS = ("artifacts", "invariants", "connections")
TABLES = {"artifacts": "artifacts", "invariants": "invariants", "connections": "connections"}
COLUMNS = {"id", "uid", "name", "purpose", "domain", "status", "kind"}


class AuthorityConflict(RuntimeError):
    """Concurrent write, stale revision, or invalid change request."""


class AuthorityIntegrityError(RuntimeError):
    """Corrupted or nonrepresentable authority."""


def canonical(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def digest(data: Any) -> str:
    return hashlib.sha256(canonical(data).encode("utf-8")).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def internal_uid(kind: str, identity: str, ordinal: int) -> str:
    # Used only as a storage key when authority does not explicitly declare UID.
    return f"internal_{uuid.uuid5(uuid.NAMESPACE_URL, kind + ':' + identity + ':' + str(ordinal)).hex}"


def _validate_json(value: Any) -> str:
    try:
        result = canonical(value)
        json.loads(result)
        return result
    except (ValueError, TypeError) as exc:
        raise AuthorityIntegrityError(f"Authority contains non-JSON value: {exc}") from exc


_SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_metadata (key TEXT PRIMARY KEY, value_json TEXT NOT NULL CHECK(json_valid(value_json)));
CREATE TABLE IF NOT EXISTS protection_state (id INTEGER PRIMARY KEY CHECK(id=1), locked INTEGER NOT NULL DEFAULT 0 CHECK(locked IN (0,1)));
CREATE TABLE IF NOT EXISTS authority_state (
  id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL DEFAULT 0,
  content_digest TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS authority_sections (
  section_key TEXT PRIMARY KEY, body_json TEXT NOT NULL CHECK(json_valid(body_json)), revision INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS blocks (
  uid TEXT PRIMARY KEY, external_id TEXT, name TEXT, domain TEXT, status TEXT, kind TEXT,
  purpose TEXT, raw_json TEXT NOT NULL CHECK(json_valid(raw_json)),
  entity_revision INTEGER NOT NULL DEFAULT 1, display_order INTEGER NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_block_id ON blocks(external_id) WHERE external_id IS NOT NULL AND external_id!='';
CREATE INDEX IF NOT EXISTS ix_block_filter ON blocks(domain,status,uid);
CREATE INDEX IF NOT EXISTS ix_block_order ON blocks(display_order,uid);
CREATE TABLE IF NOT EXISTS artifacts (
  uid TEXT PRIMARY KEY, block_uid TEXT NOT NULL REFERENCES blocks(uid) ON DELETE CASCADE,
  external_id TEXT, path TEXT, symbol TEXT, kind TEXT, type TEXT, profile_name TEXT,
  raw_json TEXT NOT NULL CHECK(json_valid(raw_json)), ordinal INTEGER NOT NULL,
  entity_revision INTEGER NOT NULL DEFAULT 1, UNIQUE(block_uid,ordinal)
);
CREATE INDEX IF NOT EXISTS ix_artifacts_owner ON artifacts(block_uid,ordinal);
CREATE INDEX IF NOT EXISTS ix_artifacts_code ON artifacts(path,symbol,kind);
CREATE TABLE IF NOT EXISTS invariants (
  uid TEXT PRIMARY KEY, block_uid TEXT NOT NULL REFERENCES blocks(uid) ON DELETE CASCADE,
  external_id TEXT, severity TEXT, type TEXT,
  raw_json TEXT NOT NULL CHECK(json_valid(raw_json)), ordinal INTEGER NOT NULL,
  entity_revision INTEGER NOT NULL DEFAULT 1, UNIQUE(block_uid,ordinal)
);
CREATE INDEX IF NOT EXISTS ix_invariants_owner ON invariants(block_uid,ordinal);
CREATE TABLE IF NOT EXISTS connections (
  uid TEXT PRIMARY KEY, source_block_uid TEXT NOT NULL REFERENCES blocks(uid) ON DELETE CASCADE,
  target_block_uid TEXT REFERENCES blocks(uid) ON DELETE SET NULL, target_literal TEXT,
  relationship TEXT, provenance TEXT,
  raw_json TEXT NOT NULL CHECK(json_valid(raw_json)), ordinal INTEGER NOT NULL,
  entity_revision INTEGER NOT NULL DEFAULT 1, UNIQUE(source_block_uid,ordinal)
);
CREATE INDEX IF NOT EXISTS ix_connections_owner ON connections(source_block_uid,ordinal);
CREATE INDEX IF NOT EXISTS ix_connections_target ON connections(target_block_uid);
CREATE TABLE IF NOT EXISTS operation_log (
  operation_id TEXT PRIMARY KEY, actor TEXT NOT NULL, reason TEXT NOT NULL,
  base_revision INTEGER NOT NULL, result_revision INTEGER NOT NULL UNIQUE,
  before_digest TEXT NOT NULL, after_digest TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operation_deltas (
  operation_id TEXT NOT NULL REFERENCES operation_log(operation_id), seq INTEGER NOT NULL,
  entity_uid TEXT NOT NULL, kind TEXT NOT NULL,
  before_json TEXT, after_json TEXT, PRIMARY KEY(operation_id,seq)
);
CREATE TABLE IF NOT EXISTS outbox_events (
  event_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL REFERENCES operation_log(operation_id),
  event_type TEXT NOT NULL, payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
  created_at TEXT NOT NULL, published_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_outbox_pending ON outbox_events(published_at,created_at);
CREATE TABLE IF NOT EXISTS import_provenance (
  entity_type TEXT NOT NULL, entity_uid TEXT NOT NULL, source TEXT,
  original_id TEXT, ordinal INTEGER, PRIMARY KEY(entity_type,entity_uid)
);
"""


class SqliteAuthorityStore:
    def __init__(self, project_root: Path, database_path: Path | None = None) -> None:
        self.project_root = Path(project_root).resolve()
        self.path = database_path or (self.project_root / ".bpfw" / "authority.sqlite")

    @contextmanager
    def connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        if not self.path.is_file():
            raise FileNotFoundError(f"SQLite authority not found: {self.path}")
        # Avoid silently creating a DB on read/write after a missing/moved path.
        mode = "rw" if write else "ro"
        from urllib.parse import quote
        conn = sqlite3.connect(f"file:{quote(str(self.path))}?mode={mode}", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            if write:
                conn.commit()
        except BaseException:
            if write:
                conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raise FileExistsError(f"Refusing to overwrite existing authority DB: {self.path}")
        conn = sqlite3.connect(str(self.path))
        try:
            conn.executescript(_SCHEMA)
            conn.execute("INSERT INTO schema_metadata VALUES(?,?)", ("schema_version", _validate_json(SCHEMA_VERSION)))
            conn.execute("INSERT INTO authority_state VALUES(1,0,?,?)", (digest({}), now()))
            conn.execute("INSERT INTO protection_state VALUES(1,0)")
            conn.commit()
        except BaseException:
            conn.close()
            self.path.unlink(missing_ok=True)
            raise
        finally:
            try: conn.close()
            except Exception: pass

    @staticmethod
    def _revision(conn: sqlite3.Connection) -> int:
        value = conn.execute("SELECT revision FROM authority_state WHERE id=1").fetchone()
        if value is None:
            raise AuthorityIntegrityError("authority_state is missing")
        return int(value["revision"])

    def locked(self) -> bool:
        with self.connect() as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='protection_state'").fetchone():
                return False  # Databases created by post1 have no logical guard yet.
            row = conn.execute("SELECT locked FROM protection_state WHERE id=1").fetchone()
            if row is None: raise AuthorityIntegrityError("Missing SQLite protection state")
            return bool(row[0])

    @staticmethod
    def _initialize_guard(conn: sqlite3.Connection) -> None:
        # Online, transactional v1-to-v1 additive migration; no authority rewrite.
        conn.execute("""CREATE TABLE IF NOT EXISTS protection_state
                        (id INTEGER PRIMARY KEY CHECK(id=1), locked INTEGER NOT NULL DEFAULT 0 CHECK(locked IN (0,1)))""")
        conn.execute("INSERT OR IGNORE INTO protection_state(id,locked) VALUES(1,0)")

    def set_locked(self, locked: bool) -> None:
        """Change the cooperative application-level SQLite authority guard."""
        with self.connect(write=True) as conn:
            self._initialize_guard(conn)
            conn.execute("UPDATE protection_state SET locked=? WHERE id=1", (int(locked),))

    @staticmethod
    def _require_unlocked(conn: sqlite3.Connection) -> None:
        SqliteAuthorityStore._initialize_guard(conn)
        state = conn.execute("SELECT locked FROM protection_state WHERE id=1").fetchone()
        if state is None: raise AuthorityIntegrityError("Missing SQLite protection state")
        if state[0]:
            from bpfw.core.catalog.access_control import has_temporary_blueprint_unlock_authorization
            if not has_temporary_blueprint_unlock_authorization():
                raise AuthorityConflict("SQLite authority is logically locked; unlock or authorize temporary edit")

    def revision(self) -> int:
        with self.connect() as conn:
            return self._revision(conn)

    @staticmethod
    def _check_schema(conn: sqlite3.Connection) -> None:
        row = conn.execute("SELECT value_json FROM schema_metadata WHERE key='schema_version'").fetchone()
        if row is None or json.loads(row["value_json"]) != SCHEMA_VERSION:
            raise AuthorityIntegrityError("Unsupported SQLite authority schema version")

    def _load_blocks(self, conn: sqlite3.Connection, rows: Sequence[sqlite3.Row]) -> list[dict[str, Any]]:
        # Three prefetches: no per-block child queries.
        blocks = {row["uid"]: json.loads(row["raw_json"]) for row in rows}
        for row in rows:
            for child in CHILD_KEYS:
                # Absent lists stay absent (explicitness is authority).
                if child in blocks[row["uid"]]:
                    blocks[row["uid"]][child] = []
        if not rows:
            return []
        uids = list(blocks)
        for start in range(0, len(uids), 400):
            fragment = uids[start:start + 400]
            placeholders = ",".join("?" for _ in fragment)
            for table in CHILD_KEYS:
                result = conn.execute(
                    f"SELECT block_uid,raw_json FROM {table} WHERE block_uid IN ({placeholders}) ORDER BY block_uid,ordinal"
                    if table != "connections" else
                    f"SELECT source_block_uid AS block_uid,raw_json FROM connections WHERE source_block_uid IN ({placeholders}) ORDER BY source_block_uid,ordinal",
                    fragment,
                )
                for child_row in result:
                    blocks[child_row["block_uid"]].setdefault(table, []).append(json.loads(child_row["raw_json"]))
        return [blocks[row["uid"]] for row in rows]

    def load_document(self) -> dict[str, Any]:
        with self.connect() as conn:
            self._check_schema(conn)
            data = {row["section_key"]: json.loads(row["body_json"]) for row in conn.execute("SELECT section_key,body_json FROM authority_sections")}
            data["blocks"] = self._load_blocks(conn, conn.execute("SELECT * FROM blocks ORDER BY display_order,uid").fetchall())
            return data

    def get_block(self, uid_or_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._check_schema(conn)
            row = conn.execute("SELECT * FROM blocks WHERE uid=?", (uid_or_id,)).fetchone()
            if row is None:
                row = conn.execute("SELECT * FROM blocks WHERE external_id=?", (uid_or_id,)).fetchone()
            return self._load_blocks(conn, [row])[0] if row else None

    def list_blocks(self, *, domain: str | None = None, status: str | None = None, search: str | None = None,
                    limit: int = 100, after: tuple[int, str] | None = None) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be in [1, 1000]")
        query = "SELECT * FROM blocks WHERE 1=1"
        args: list[Any] = []
        for key, value in (("domain", domain), ("status", status)):
            if value is not None:
                query += f" AND {key}=?"; args.append(value)
        if search:
            query += " AND (name LIKE ? ESCAPE '\\' OR external_id LIKE ? ESCAPE '\\' OR purpose LIKE ? ESCAPE '\\')"
            pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            args.extend([pattern, pattern, pattern])
        if after:
            query += " AND (display_order,uid)>(?,?)"; args.extend(after)
        query += " ORDER BY display_order,uid LIMIT ?"; args.append(limit)
        with self.connect() as conn:
            self._check_schema(conn)
            return self._load_blocks(conn, conn.execute(query, args).fetchall())

    @staticmethod
    def _identity(block: dict[str, Any], ordinal: int) -> str:
        explicit = block.get("uid")
        if explicit is not None and str(explicit).strip():
            return str(explicit)
        return internal_uid("block", str(block.get("id") or ""), ordinal)

    @staticmethod
    def _split_children(block: dict[str, Any]) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
        raw = dict(block)
        children: dict[str, list[dict[str, Any]]] = {}
        for key in CHILD_KEYS:
            if key in raw:
                value = raw[key]
                raw[key] = []  # presence marker: empty vs absent survives migration
                if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
                    raise AuthorityIntegrityError(f"{key} must be a list of objects")
                children[key] = value
        return raw, children

    @staticmethod
    def _save_block(conn: sqlite3.Connection, uid: str, block: dict[str, Any], ordinal: int,
                    entity_revision: int) -> None:
        raw, children = SqliteAuthorityStore._split_children(block)
        conn.execute("""INSERT INTO blocks(uid,external_id,name,domain,status,kind,purpose,raw_json,entity_revision,display_order,updated_at)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(uid) DO UPDATE SET external_id=excluded.external_id,name=excluded.name,
                       domain=excluded.domain,status=excluded.status,kind=excluded.kind,purpose=excluded.purpose,
                       raw_json=excluded.raw_json,entity_revision=excluded.entity_revision,
                       display_order=excluded.display_order,updated_at=excluded.updated_at""",
                     (uid, str(raw.get("id") or "") or None, raw.get("name"), raw.get("domain"), raw.get("status"),
                      raw.get("kind"), raw.get("purpose"), _validate_json(raw), entity_revision, ordinal, now()))
        # Children are NOT synthesized from legacy code metadata.
        for table in CHILD_KEYS:
            conn.execute(f"DELETE FROM {table} WHERE " + ("source_block_uid=?" if table == "connections" else "block_uid=?"), (uid,))
            for i, obj in enumerate(children.get(table, [])):
                child_uid = str(obj.get("uid") or internal_uid(table, uid + ":" + str(obj.get("id") or ""), i))
                if table == "artifacts":
                    conn.execute("""INSERT INTO artifacts(uid,block_uid,external_id,path,symbol,kind,type,profile_name,raw_json,ordinal)
                                    VALUES(?,?,?,?,?,?,?,?,?,?)""",
                                 (child_uid, uid, obj.get("id"), obj.get("path"), obj.get("symbol"), obj.get("kind"),
                                  obj.get("type"), obj.get("profile"), _validate_json(obj), i))
                elif table == "invariants":
                    conn.execute("""INSERT INTO invariants(uid,block_uid,external_id,severity,type,raw_json,ordinal)
                                    VALUES(?,?,?,?,?,?,?)""",
                                 (child_uid, uid, obj.get("id"), obj.get("severity"), obj.get("type"), _validate_json(obj), i))
                else:
                    conn.execute("""INSERT INTO connections(uid,source_block_uid,target_literal,relationship,provenance,raw_json,ordinal)
                                    VALUES(?,?,?,?,?,?,?)""",
                                 (child_uid, uid, str(obj.get("target") or ""), obj.get("relationship"),
                                  obj.get("provenance"), _validate_json(obj), i))

    @staticmethod
    def _resolve_connections(conn: sqlite3.Connection) -> None:
        conn.execute("""UPDATE connections SET target_block_uid=(
            SELECT b.uid FROM blocks b WHERE b.uid=connections.target_literal OR b.external_id=connections.target_literal
            LIMIT 1)""")

    def _stream_digest(self, conn: sqlite3.Connection) -> str:
        """Canonical document hash using bounded 400-block batches.

        Same digest as canonical(load_document), but memory does not grow with
        the full authority size. Scans are still O(N) until a Merkle index exists.
        """
        h = hashlib.sha256()
        h.update(b"{")
        section_rows = conn.execute("SELECT section_key,body_json FROM authority_sections ORDER BY section_key").fetchall()
        sections = {r["section_key"]: json.loads(r["body_json"]) for r in section_rows}
        keys = sorted([*sections, "blocks"])
        for ki, key in enumerate(keys):
            if ki: h.update(b",")
            h.update(canonical(key).encode("utf-8"))
            h.update(b":")
            if key != "blocks":
                h.update(canonical(sections[key]).encode("utf-8"))
                continue
            h.update(b"[")
            cursor = conn.execute("SELECT * FROM blocks ORDER BY display_order,uid")
            first = True
            while True:
                chunk = cursor.fetchmany(400)
                if not chunk: break
                for block in self._load_blocks(conn, chunk):
                    if not first: h.update(b",")
                    first = False
                    h.update(canonical(block).encode("utf-8"))
            h.update(b"]")
        h.update(b"}")
        return h.hexdigest()

    @staticmethod
    def _record(conn: sqlite3.Connection, *, actor: str, reason: str, before: int,
                before_digest: str, after_digest: str, deltas: list[tuple[str,str,Any,Any]]) -> None:
        op = f"op_{uuid.uuid4().hex}"
        timestamp = now()
        conn.execute("INSERT INTO operation_log VALUES(?,?,?,?,?,?,?,?)",
                     (op, actor, reason, before, before + 1, before_digest, after_digest, timestamp))
        for seq, (uid, kind, old, new) in enumerate(deltas):
            conn.execute("INSERT INTO operation_deltas VALUES(?,?,?,?,?,?)",
                         (op, seq, uid, kind, _validate_json(old) if old is not None else None,
                          _validate_json(new) if new is not None else None))
        conn.execute("INSERT INTO outbox_events VALUES(?,?,?,?,?,NULL)",
                     (f"evt_{uuid.uuid4().hex}", op, "authority.changed",
                      _validate_json({"operation_id": op, "actor": actor, "revision": before + 1,
                                      "entity_uids": [d[0] for d in deltas]}), timestamp))
        conn.execute("UPDATE authority_state SET revision=?,content_digest=?,updated_at=? WHERE id=1",
                     (before + 1, after_digest, timestamp))

    def import_document(self, data: dict[str, Any], *, actor: str = "migration", origins: dict[str, str] | None = None) -> int:
        """Initial import only into an empty DB, full transaction, lossless raw JSON."""
        if not isinstance(data, dict) or not isinstance(data.get("blocks", []), list):
            raise AuthorityIntegrityError("Expected Blueprint document with blocks list")
        with self.connect(write=True) as conn:
            self._check_schema(conn)
            self._require_unlocked(conn)
            if self._revision(conn) or conn.execute("SELECT 1 FROM blocks LIMIT 1").fetchone():
                raise AuthorityConflict("Import only allowed on an empty database")
            seen: set[str] = set()
            for key, value in data.items():
                if key != "blocks":
                    conn.execute("INSERT INTO authority_sections VALUES(?,?,1)", (key, _validate_json(value)))
            for ordinal, block in enumerate(data.get("blocks", [])):
                if not isinstance(block, dict):
                    raise AuthorityIntegrityError("Each block must be an object")
                uid = self._identity(block, ordinal)
                if uid in seen:
                    raise AuthorityIntegrityError(f"Duplicate block UID {uid!r}")
                seen.add(uid)
                self._save_block(conn, uid, block, ordinal, 1)
                conn.execute("INSERT INTO import_provenance VALUES(?,?,?,?,?)",
                             ("block", uid, (origins or {}).get(block.get("id"), actor), block.get("id"), ordinal))
            self._resolve_connections(conn)
            new_digest = digest(data)
            self._record(conn, actor=actor, reason="initial import", before=0, before_digest=digest({}),
                         after_digest=new_digest, deltas=[("root", "import", None, {"blocks": len(seen)})])
        return 1

    def apply_patches(self, edits: Sequence[Mapping[str, Any]], *, actor: str = "batch",
                      reason: str = "bulk edit", expected_revision: int | None = None,
                      dry_run: bool = False) -> dict[str, Any]:
        """Apply cell patches as one transaction; absence/null/clear are distinct.

        Each edit requires ``uid``, ``field``, ``op=set|clear``, optionally
        ``expected_entity_revision``. Immutable uid and child arrays are not
        editable via CSV (must use a typed structural operation).
        """
        from bpfw.core.automation.engine import _set_path, _remove_path, _has_path
        if not edits:
            return {"changed": 0, "changes": [], "revision": self.revision()}
        # BEGIN IMMEDIATE also for previews gives a coherent read across edits;
        # previews are rolled back via a special exception below.
        class _PreviewRollback(Exception): pass
        outcome: dict[str, Any] = {}
        try:
            with self.connect(write=True) as conn:
                self._check_schema(conn)
                self._require_unlocked(conn)
                base = self._revision(conn)
                if expected_revision is not None and base != expected_revision:
                    raise AuthorityConflict(f"Stale authority revision: expected {expected_revision}, found {base}")
                current: dict[str, sqlite3.Row] = {}
                changed: dict[str, dict[str, Any]] = {}
                before: dict[str, dict[str, Any]] = {}
                diff: list[dict[str, Any]] = []
                for edit in edits:
                    uid = str(edit.get("uid") or "")
                    row = current.get(uid)
                    if row is None:
                        row = conn.execute("SELECT * FROM blocks WHERE uid=?", (uid,)).fetchone()
                        if row is None:
                            row = conn.execute("SELECT * FROM blocks WHERE external_id=?", (uid,)).fetchone()
                    if row is None:
                        raise AuthorityConflict(f"Unknown block UID/ID: {uid!r}")
                    actual_uid = row["uid"]
                    current[actual_uid] = row
                    current[uid] = row
                    exp = edit.get("expected_entity_revision")
                    if exp is not None and int(exp) != row["entity_revision"]:
                        raise AuthorityConflict(f"Stale block {uid}: expected entity revision {exp}, found {row['entity_revision']}")
                    field = str(edit.get("field") or "")
                    if not field or field.split(".")[0] in {"uid", "id", *CHILD_KEYS} or ".." in field:
                        raise AuthorityConflict(f"Forbidden or invalid field path: {field!r}")
                    op = str(edit.get("op") or "set")
                    if op not in {"set", "clear"}:
                        raise AuthorityConflict(f"Unsupported edit operation: {op}")
                    if actual_uid not in changed:
                        changed[actual_uid] = json.loads(row["raw_json"])
                        before[actual_uid] = dict(changed[actual_uid])
                    item = changed[actual_uid]
                    existed = _has_path(item, field)
                    old = json.loads(canonical(_get_field(item, field))) if existed else None
                    if op == "set":
                        did_change = _set_path(item, field, edit.get("value"))
                    else:
                        did_change = _remove_path(item, field)
                    if did_change:
                        diff.append({"uid": actual_uid, "field": field, "op": op, "before_present": existed,
                                     "before": old, "after_present": op == "set", "after": edit.get("value") if op == "set" else None})
                changed = {uid: b for uid, b in changed.items() if b != before[uid]}
                if changed:
                    for uid, block in changed.items():
                        r = current[uid]
                        # No child rewrite here: patch paths explicitly exclude children.
                        conn.execute("""UPDATE blocks SET external_id=?,name=?,domain=?,status=?,kind=?,purpose=?,
                                raw_json=?,entity_revision=entity_revision+1,updated_at=? WHERE uid=?""",
                                     (block.get("id"), block.get("name"), block.get("domain"), block.get("status"),
                                      block.get("kind"), block.get("purpose"), _validate_json(block), now(), uid))
                    after_digest = self._stream_digest(conn)
                    previous = conn.execute("SELECT content_digest FROM authority_state WHERE id=1").fetchone()[0]
                    self._record(conn, actor=actor, reason=reason, before=base, before_digest=previous,
                                 after_digest=after_digest, deltas=[(u, "block.patch", before[u], changed[u]) for u in changed])
                    base += 1
                outcome = {"changed": len(changed), "cells": len(diff), "revision": base, "changes": diff}
                if dry_run:
                    raise _PreviewRollback()
        except _PreviewRollback:
            pass
        return outcome

    def replace_document(self, new_data: dict[str, Any], *, actor: str = "automation", reason: str = "replace",
                         expected_revision: int | None = None, origins: dict[str, str] | None = None) -> int:
        """Compatibility transaction: update only changed blocks and sections."""
        if not isinstance(new_data, dict) or not isinstance(new_data.get("blocks", []), list):
            raise AuthorityIntegrityError("Expected a document with blocks list")
        with self.connect(write=True) as conn:
            self._check_schema(conn)
            self._require_unlocked(conn)
            base = self._revision(conn)
            if expected_revision is not None and expected_revision != base:
                raise AuthorityConflict(f"Expected revision {expected_revision}, found {base}")
            old_sections = {r["section_key"]: json.loads(r["body_json"]) for r in conn.execute("SELECT * FROM authority_sections")}
            old_rows = conn.execute("SELECT * FROM blocks ORDER BY display_order,uid").fetchall()
            old_blocks = self._load_blocks(conn, old_rows)
            old_by_uid = {r["uid"]: (r, b) for r, b in zip(old_rows, old_blocks)}
            old_id_to_uid = {r["external_id"]: r["uid"] for r in old_rows if r["external_id"]}
            new_by_uid: dict[str, tuple[int, dict[str, Any]]] = {}
            for i, b in enumerate(new_data["blocks"]):
                if not isinstance(b, dict): raise AuthorityIntegrityError("Invalid block object")
                uid = str(b["uid"]) if b.get("uid") else (old_id_to_uid.get(b.get("id")) or self._identity(b, i))
                if uid in new_by_uid: raise AuthorityConflict(f"Duplicate UID: {uid}")
                new_by_uid[uid] = (i, b)
            old_data = {**old_sections, "blocks": old_blocks}
            if old_data == new_data:
                return base
            deltas: list[tuple[str,str,Any,Any]] = []
            for key in old_sections.keys() - new_data.keys():
                conn.execute("DELETE FROM authority_sections WHERE section_key=?", (key,))
                deltas.append((key,"section.delete",old_sections[key],None))
            for key, value in new_data.items():
                if key == "blocks": continue
                if key not in old_sections or old_sections[key] != value:
                    conn.execute("""INSERT INTO authority_sections VALUES(?,?,1)
                                    ON CONFLICT(section_key) DO UPDATE SET body_json=excluded.body_json, revision=revision+1""",
                                 (key, _validate_json(value)))
                    deltas.append((key,"section.set",old_sections.get(key),value))
            # Deletes first avoids transient unique external_id violations from renames.
            for uid in old_by_uid.keys() - new_by_uid.keys():
                conn.execute("DELETE FROM blocks WHERE uid=?", (uid,))
                deltas.append((uid,"block.delete",old_by_uid[uid][1],None))
            for uid, (ordinal, block) in new_by_uid.items():
                previous = old_by_uid.get(uid)
                if previous and previous[1] == block and previous[0]["display_order"] == ordinal:
                    continue
                self._save_block(conn, uid, block, ordinal, previous[0]["entity_revision"] + 1 if previous else 1)
                deltas.append((uid,"block.upsert",previous[1] if previous else None,block))
            if origins is not None:
                for uid, (_, block) in new_by_uid.items():
                    logical_source = origins.get(block.get("id"))
                    if logical_source is not None:
                        conn.execute("""INSERT INTO import_provenance(entity_type,entity_uid,source,original_id,ordinal)
                                        VALUES('block',?,?,?,?) ON CONFLICT(entity_type,entity_uid)
                                        DO UPDATE SET source=excluded.source""",
                                     (uid, logical_source, block.get("id"), new_by_uid[uid][0]))
                for uid in old_by_uid.keys() - new_by_uid.keys():
                    conn.execute("DELETE FROM import_provenance WHERE entity_type='block' AND entity_uid=?", (uid,))
            self._resolve_connections(conn)
            prev = conn.execute("SELECT content_digest FROM authority_state WHERE id=1").fetchone()[0]
            self._record(conn, actor=actor, reason=reason, before=base, before_digest=prev,
                         after_digest=digest(new_data), deltas=deltas)
            return base + 1

    def doctor(self) -> dict[str, Any]:
        with self.connect() as conn:
            self._check_schema(conn)
            integrity = [r[0] for r in conn.execute("PRAGMA integrity_check").fetchall()]
            foreign_keys = [tuple(r) for r in conn.execute("PRAGMA foreign_key_check").fetchall()]
            duplicates = [dict(r) for r in conn.execute("""SELECT path,symbol,kind,COUNT(*) AS count
                       FROM artifacts WHERE path IS NOT NULL AND path!='' GROUP BY path,symbol,kind HAVING COUNT(*)>1""")]
            dangling = [dict(r) for r in conn.execute("""SELECT uid,target_literal FROM connections
                       WHERE target_literal!='' AND target_block_uid IS NULL""")]
            counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("blocks", "artifacts", "invariants", "connections", "operation_log", "outbox_events")}
            revision = self._revision(conn)
            recorded = conn.execute("SELECT content_digest FROM authority_state WHERE id=1").fetchone()[0]
            computed = self._stream_digest(conn)
            projection_mismatches: list[str] = []
            for r in conn.execute("SELECT uid,raw_json,external_id,name,purpose,domain,status,kind FROM blocks"):
                raw = json.loads(r["raw_json"])
                for col, key in (("external_id", "id"), ("name", "name"), ("purpose", "purpose"),
                                 ("domain", "domain"), ("status", "status"), ("kind", "kind")):
                    value = raw.get(key)
                    if (str(value or "") or None) != (str(r[col] or "") or None):
                        projection_mismatches.append(f"block:{r['uid']}:{col}")
            for table in ("artifacts", "invariants", "connections"):
                for r in conn.execute(f"SELECT uid,raw_json FROM {table}"):
                    try: json.loads(r["raw_json"])
                    except (TypeError, ValueError): projection_mismatches.append(f"{table}:{r['uid']}:raw_json")
            return {"backend": "sqlite", "schema_version": SCHEMA_VERSION, "revision": revision,
                    "logically_locked": self.locked(),
                    "integrity": integrity, "foreign_key_violations": foreign_keys,
                    "digest_matches": computed == recorded, "projection_mismatches": projection_mismatches, "counts": counts,
                    "duplicate_artifacts": duplicates, "unresolved_connections": dangling,
                    "database_bytes": self.path.stat().st_size,
                    "ok": integrity == ["ok"] and not foreign_keys and computed == recorded and not projection_mismatches}

    def backup(self, destination: Path) -> None:
        """Consistent SQLite backup (not raw copy while connections write)."""
        destination = destination.resolve()
        if destination == self.path.resolve() or destination.exists():
            raise FileExistsError("Backup destination must be a new distinct file")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as src:
            with sqlite3.connect(str(destination)) as dst:
                src.backup(dst)


def _get_field(obj: dict[str, Any], path: str) -> Any:
    current: Any = obj
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current
