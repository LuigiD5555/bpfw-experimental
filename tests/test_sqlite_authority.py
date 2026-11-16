"""SQLite authority migration, atomicity, CSV editing and legacy compatibility."""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from bpfw.core.authority.sqlite.store import SqliteAuthorityStore, AuthorityConflict, AuthorityIntegrityError
from bpfw.core.authority.sqlite.migration import migrate_legacy, active_backend
from bpfw.core.authority.sqlite.batch import export_blocks, import_csv
from bpfw.core.blueprint_engine.engine import BlueprintEngine
from bpfw.core.catalog.domain.repository import BlueprintRepository
from bpfw.core.catalog.loader import BlueprintLoader
from bpfw.core.catalog.writer import write_blueprint


@pytest.fixture
def example(tmp_path):
    root = tmp_path / "myproject"
    path = root / ".bpfw" / "blueprint.yaml"
    path.parent.mkdir(parents=True)
    data = {
        "version": 2,
        "project": {"name": "sample", "language": "python"},
        "policy": {"allowed_statuses": ["active", "experimental", "legacy", "deprecated"], "x_custom": {"yes": True}},
        "profiles": {"shared": {"type": "code", "language": "python"}},
        "authority": {"layout": "single"},
        "metadata_extra": {"nested": [1, None, {"key": False}]},
        "blocks": [
            {"id": "compute", "uid": "bp_compute", "purpose": "calculate", "status": "active", "domain": "core",
             "artifacts": [{"uid": "art_a", "id": "code_impl", "path": "src/mod.py", "symbol": "compute", "kind": "function", "properties": {"z": 1}}],
             "invariants": [{"uid": "inv_a", "id": "unique", "description": "one", "extra_data": True}],
             "connections": [{"target": "missing_block", "relationship": "calls"}, {"uid": "c2", "target": "read"}],
             "code": {"path": "src/legacy.py", "symbol": "compute", "kind": "function"},
             "extensions": {"custom": [None, 9]}},
            {"id": "read", "purpose": None, "domain": "core", "artifacts": []},
        ],
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return root, data, path


def migrated(example):
    root, original, path = example
    yaml_bytes = path.read_bytes()
    report = migrate_legacy(root, apply=True)
    assert report["activated"]
    assert path.read_bytes() == yaml_bytes
    return root, original, path, SqliteAuthorityStore(root)


def test_preview_no_side_effects(example):
    root, _, _ = example
    preview = migrate_legacy(root)
    assert preview["can_activate"] and preview["blocks"] == 2
    assert not (root / ".bpfw" / "authority.sqlite").exists()
    assert active_backend(root) == "yaml"


def test_lossless_migration_and_loader(example):
    root, data, _, store = migrated(example)
    assert store.load_document() == data
    assert store.get_block("compute") == data["blocks"][0]
    assert store.get_block("bp_compute") == data["blocks"][0]
    assert BlueprintRepository(root).load().raw_data == data
    from bpfw.core.automation.profiles import strip_ephemeral
    assert strip_ephemeral(BlueprintLoader(root).load().data) == data
    assert store.doctor()["ok"]
    assert store.doctor()["unresolved_connections"][0]["target_literal"] == "missing_block"
    with pytest.raises(AuthorityConflict):
        migrate_legacy(root, apply=True)


def test_no_unexpected_legacy_write(example):
    root, data, path, store = migrated(example)
    before = path.read_bytes()
    with pytest.raises(AuthorityConflict):
        write_blueprint(path, data)
    assert path.read_bytes() == before
    assert store.revision() == 1


def test_filtered_get_list_are_read_only(example):
    root, data, _, store = migrated(example)
    assert len(store.list_blocks(domain="core", limit=1)) == 1
    assert len(store.list_blocks(status="active")) == 1
    assert len(store.list_blocks(search="compute")) == 1
    assert store.get_block("ghost") is None
    assert store.revision() == 1


def test_atomic_patch_and_doctor(example):
    root, data, _, store = migrated(example)
    engine = BlueprintEngine(root)
    changes = [{"uid": "bp_compute", "field": "status", "op": "set", "value": "deprecated", "expected_entity_revision": 1},
               {"uid": "bp_compute", "field": "new_custom.field", "op": "set", "value": False, "expected_entity_revision": 1}]
    preview = engine.preview_authority_patches(changes)
    assert preview["changed"] == 1
    assert store.revision() == 1
    assert store.get_block("compute")["status"] == "active"
    result = engine.apply_authority_patches(changes)
    assert result["changed"] == 1 and result["revision"] == 2
    assert store.get_block("compute")["new_custom"]["field"] is False
    assert store.doctor()["ok"]
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM operation_log").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM outbox_events").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM operation_deltas WHERE operation_id=(SELECT operation_id FROM operation_log WHERE result_revision=2)").fetchone()[0] == 1


def test_stale_revision_rollback(example):
    root, data, _, store = migrated(example)
    with pytest.raises(AuthorityConflict):
        store.apply_patches([{"uid": "bp_compute", "field": "status", "value": "deprecated", "expected_entity_revision": 0}])
    assert store.load_document() == data
    assert store.revision() == 1
    with pytest.raises(AuthorityConflict):
        store.apply_patches([{"uid": "bp_compute", "field": "status", "value": "legacy"},
                             {"uid": "ghost", "field": "name", "value": "oops"}])
    assert store.load_document() == data
    assert store.doctor()["ok"]


def test_bulk_csv_roundtrip_and_stale_import(example):
    root, data, _, store = migrated(example)
    out = root / "sheet.csv"
    assert export_blocks(store, out) == 2
    assert import_csv(store, out)["changed"] == 0
    with out.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle); records = list(reader); fields = reader.fieldnames
    records[0]["status"] = "deprecated"
    records[0]["purpose"] = ""
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(records)
    assert import_csv(store, out)["cells"] == 2
    assert store.revision() == 1
    assert import_csv(store, out, apply=True)["changed"] == 1
    assert store.get_block("compute")["status"] == "deprecated"
    assert "purpose" not in store.get_block("compute")
    with pytest.raises(AuthorityConflict):
        import_csv(store, out, apply=True)
    assert store.doctor()["ok"]


def test_explicit_null_and_clear(example):
    root, data, _, store = migrated(example)
    store.apply_patches([{"uid": "read", "field": "purpose", "op": "clear"},
                         {"uid": "read", "field": "status", "op": "set", "value": None}])
    block = store.get_block("read")
    assert "purpose" not in block and "status" in block and block["status"] is None
    assert store.doctor()["ok"]


def test_full_replace_incremental_and_conflict(example):
    root, data, _, store = migrated(example)
    snapshot = store.load_document()
    assert BlueprintEngine(root).replace_authority_document(snapshot, reason="noop") == 1
    snapshot["blocks"][1]["domain"] = "api"
    assert BlueprintEngine(root).replace_authority_document(snapshot, reason="edit", expected_revision=1) == 2
    assert store.get_block("read")["domain"] == "api"
    with store.connect() as conn:
        assert conn.execute("SELECT entity_revision FROM blocks WHERE uid='bp_compute'").fetchone()[0] == 1
    with pytest.raises(AuthorityConflict):
        BlueprintEngine(root).replace_authority_document(snapshot, reason="stale", expected_revision=1)
    assert store.doctor()["ok"]


def test_backup_and_corruption_detection(example):
    root, _, _, store = migrated(example)
    dest = root / "copy.sqlite"
    store.backup(dest)
    with sqlite3.connect(dest) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with store.connect(write=True) as conn:
        conn.execute("UPDATE blocks SET name='tamper' WHERE uid='bp_compute'")
    assert not store.doctor()["ok"]


def test_duplicate_ids_prevent_activation(example):
    root, data, path = example
    data["blocks"][1]["id"] = "compute"
    path.write_text(yaml.safe_dump(data))
    report = migrate_legacy(root)
    assert not report["can_activate"] or report["duplicate_ids"]
    with pytest.raises(Exception):
        migrate_legacy(root, apply=True)
    assert not (root / ".bpfw" / "manifest.json").exists()


def test_patch_csv_explicit_and_atomic_error(example):
    root, _, _, store = migrated(example)
    csv_file = root / "changes.csv"
    csv_file.write_text("uid,revision,field,op,value\nbp_compute,1,domain,set,backend\nread,1,status,set,experimental\n")
    assert import_csv(store, csv_file)["changed"] == 2
    assert store.revision() == 1
    assert import_csv(store, csv_file, apply=True)["changed"] == 2
    assert store.get_block("read")["status"] == "experimental"
    assert store.doctor()["ok"]


def test_sharded_authority_migration_roundtrip(tmp_path):
    root = tmp_path / "sharded"
    source = root / ".bpfw" / "blueprint.yaml"
    shard = root / ".bpfw" / "blocks" / "core.yaml"
    shard.parent.mkdir(parents=True)
    source.write_text(yaml.safe_dump({
        "version": 2, "project": {"name": "sharded"},
        "authority": {"layout": "sharded", "shard_strategy": "domain", "default_shard": ".bpfw/blocks/core.yaml"},
        "includes": [".bpfw/blocks/core.yaml"],
    }))
    shard.write_text(yaml.safe_dump({"blocks": [{"id": "a", "uid": "bp_a", "purpose": "execute", "status": "active"}]}))
    original = BlueprintRepository(root).load().raw_data
    initial_bytes = (source.read_bytes(), shard.read_bytes())
    migrate_legacy(root, apply=True)
    assert SqliteAuthorityStore(root).load_document() == original
    assert (source.read_bytes(), shard.read_bytes()) == initial_bytes
    assert SqliteAuthorityStore(root).doctor()["ok"]


def test_stable_legacy_uid_when_reordering(example):
    root, _, _, store = migrated(example)
    before = store.get_block("read")
    with store.connect() as conn:
        uid = conn.execute("SELECT uid FROM blocks WHERE external_id='read'").fetchone()[0]
    data = store.load_document()
    data["blocks"] = list(reversed(data["blocks"]))
    store.replace_document(data, expected_revision=1)
    with store.connect() as conn:
        assert conn.execute("SELECT uid FROM blocks WHERE external_id='read'").fetchone()[0] == uid
    assert store.doctor()["ok"]
