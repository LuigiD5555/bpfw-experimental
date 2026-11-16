"""Spreadsheet-compatible, optimistic CSV bulk editing of SQLite authority."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .store import SqliteAuthorityStore, AuthorityConflict, canonical

FIELDS = ("uid", "id", "revision", "name", "purpose", "domain", "status", "kind")
PATCH_FIELDS = {"name", "purpose", "domain", "status", "kind"}


def export_blocks(store: SqliteAuthorityStore, filename: Path, *, domain: str | None = None) -> int:
    """Export simple scalar fields with stable UID and optimistic version."""
    if filename.exists():
        raise FileExistsError(f"Refusing to overwrite CSV: {filename}")
    filename.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    baseline: dict[str, Any] = {}
    baseline_file = filename.with_name(filename.name + ".baseline.json")
    if baseline_file.exists():
        raise FileExistsError(f"Refusing to overwrite CSV baseline: {baseline_file}")
    with filename.open("x", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        after = None
        while True:
            with store.connect() as conn:
                params: list[Any] = []
                sql = "SELECT uid,external_id,name,purpose,domain,status,kind,entity_revision,display_order,raw_json FROM blocks WHERE 1=1"
                if domain is not None:
                    sql += " AND domain=?"; params.append(domain)
                if after is not None:
                    sql += " AND (display_order,uid)>(?,?)"; params.extend(after)
                sql += " ORDER BY display_order,uid LIMIT 400"
                rows = conn.execute(sql, params).fetchall()
            for row in rows:
                baseline[row["uid"]] = {"revision": row["entity_revision"], "id": row["external_id"] or "",
                                         "fields": {key: row[key] for key in PATCH_FIELDS},
                                         "present": {key: key in json.loads(row["raw_json"]) for key in PATCH_FIELDS}}
                writer.writerow({"uid": row["uid"], "id": row["external_id"] or "", "revision": row["entity_revision"],
                                 **{key: row[key] if row[key] is not None else "" for key in PATCH_FIELDS}})
                count += 1
            if not rows: break
            after = (rows[-1]["display_order"], rows[-1]["uid"])
    baseline_file.write_text(json.dumps({"schema": "bpfw.table-baseline/v1", "blocks": baseline},
                                         ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return count


def import_csv(store: SqliteAuthorityStore, filename: Path, *, apply: bool = False) -> dict[str, Any]:
    """Read CSV patch operations; blank means no update, CLEAR means removal.

    Input form: uid,revision,field,op,value. ``set`` accepts a JSON literal
    (e.g. null, false, 123, quoted string), otherwise plain text is used.
    """
    rows: list[dict[str, Any]] = []
    with filename.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        columns = set(reader.fieldnames or [])
        if set(FIELDS).issubset(columns) and "field" not in columns:
            return _import_table(store, filename, reader, apply=apply)
        if not {"uid", "revision", "field", "op", "value"}.issubset(columns):
            raise ValueError("CSV needs either exported table columns or uid,revision,field,op,value")
        for line, row in enumerate(reader, 2):
            if not row.get("uid") or not row.get("revision"):
                raise ValueError(f"CSV line {line}: UID and revision required")
            field = str(row.get("field") or "")
            if field not in PATCH_FIELDS and not field.startswith(("intent.", "properties.", "failure_behavior.", "analysis.", "uniqueness.")):
                raise ValueError(f"CSV line {line}: unsupported field {field!r}")
            operation = str(row.get("op") or "set").strip()
            if operation not in {"set", "clear"}:
                raise ValueError(f"CSV line {line}: unsupported op {operation!r}")
            raw = row.get("value") or ""
            if operation == "set":
                try: value = json.loads(raw)
                except json.JSONDecodeError: value = raw
            else:
                value = None
            rows.append({"uid": row["uid"], "expected_entity_revision": int(row["revision"]),
                         "field": field, "op": operation, "value": value})
    if len(rows) > 100000:
        raise ValueError("CSV patch contains too many operations (100000 maximum)")
    # Revisions are tested for *all* rows even when edits would produce no change.
    from bpfw.core.blueprint_engine.engine import BlueprintEngine
    engine = BlueprintEngine(store.project_root)
    if apply:
        return engine.apply_authority_patches(rows, reason=f"CSV import {filename.name}")
    return engine.preview_authority_patches(rows)


def _import_table(store: SqliteAuthorityStore, filename: Path, reader: csv.DictReader,
                  *, apply: bool) -> dict[str, Any]:
    """Convert a spreadsheet table diff into safe logical operations."""
    baseline_file = filename.with_name(filename.name + ".baseline.json")
    if not baseline_file.is_file():
        raise ValueError(f"Missing CSV baseline file: {baseline_file}. No data changed.")
    baseline = json.loads(baseline_file.read_text(encoding="utf-8"))
    if baseline.get("schema") != "bpfw.table-baseline/v1":
        raise ValueError("Invalid CSV baseline schema")
    originals = baseline["blocks"]
    seen: set[str] = set()
    edits: list[dict[str, Any]] = []
    for line, row in enumerate(reader, 2):
        uid = str(row.get("uid") or "")
        original = originals.get(uid)
        if not uid or original is None or uid in seen:
            raise ValueError(f"CSV line {line}: UID unknown or repeated")
        seen.add(uid)
        if str(row.get("id") or "") != original["id"] or str(row.get("revision") or "") != str(original["revision"]):
            raise ValueError(f"CSV line {line}: id/revision cannot be edited")
        for field in PATCH_FIELDS:
            value = row.get(field)
            if value is None:
                raise ValueError(f"CSV line {line}: missing {field} column")
            previous = original["fields"].get(field)
            previous_text = "" if previous is None else str(previous)
            if value == previous_text:
                continue
            edits.append({"uid": uid, "expected_entity_revision": original["revision"],
                          "field": field, "op": "set" if value else "clear", "value": value if value else None})
    # Missing rows are not interpreted as requests to delete blocks.
    if len(edits) > 100000:
        raise ValueError("Too many spreadsheet changes")
    from bpfw.core.blueprint_engine.engine import BlueprintEngine
    engine = BlueprintEngine(store.project_root)
    if apply:
        return engine.apply_authority_patches(edits, reason=f"spreadsheet import {filename.name}")
    return engine.preview_authority_patches(edits)
