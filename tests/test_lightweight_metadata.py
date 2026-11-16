"""Lighter metadata: markup granularity, compact change records and compact history."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import yaml
from pytest_readable import readable

from bpfw.core.authority.sqlite.compaction import apply_compaction, plan_compaction
from bpfw.core.authority.sqlite.history import project_outbox
from bpfw.core.authority.sqlite.migration import migrate_legacy
from bpfw.core.authority.sqlite.regranulate import apply_regranulation, plan_regranulation
from bpfw.core.authority.sqlite.store import (
    PARTIAL_MARKER,
    SqliteAuthorityStore,
    decode_delta_payload,
    encode_delta_payload,
    field_level_change,
)
from bpfw.core.history.compaction import apply_history_compaction
from bpfw.core.history.ledger import (
    HistoryLedger,
    _history_files,
    _read_history_file,
    capture_artifact_state,
    read_impact_closure,
)
from bpfw.core.source.tree_sitter_adapter import extract_units, normalize_markup_granularity

pytest.importorskip("tree_sitter_html")
pytest.importorskip("tree_sitter_css")

TEMPLATE = """<div class="page"><div class="head"><h1>Title</h1></div>
<form id="login"><div class="field"><label>Name</label><input name="name"></div>
<button type="submit">Go</button></form>
<section><div><p>Text</p></div></section></div>
"""

STYLESHEET = """.page { color: red; }
@media (max-width: 600px) { .page { color: blue; } .head { margin: 0; } }
@keyframes spin { from { opacity: 0; } to { opacity: 1; } }
"""


def _units(tmp_path: Path, language: str, text: str, granularity: str):
    name = "page.html" if language == "html" else "page.css"
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    units, has_error = extract_units(language, path, Path(name), markup_granularity=granularity)
    assert not has_error
    return units


@readable(
    intention="Keep only meaningful HTML elements without changing the identity of the ones kept.",
    steps=["Extract a template with the full and the meaningful profiles."],
    criteria=["Wrappers disappear; forms, controls, buttons, sections and id elements stay with identical symbols "
              "and hashes; each kept element points to its nearest kept ancestor."],
)
def test_meaningful_html_keeps_identity(tmp_path):
    full = {unit.symbol: unit for unit in _units(tmp_path, "html", TEMPLATE, "full")}
    meaningful = _units(tmp_path, "html", TEMPLATE, "meaningful")
    symbols = {unit.symbol for unit in meaningful}
    assert symbols == {
        "div[1]/form#login", "div[1]/form#login/div[1]/input[1]", "div[1]/form#login/button[1]", "div[1]/section[1]",
    }
    for unit in meaningful:
        assert full[unit.symbol].normalized_body_hash == unit.normalized_body_hash
    by_symbol = {unit.symbol: unit for unit in meaningful}
    assert by_symbol["div[1]/form#login/div[1]/input[1]"].parent_unit_id == by_symbol["div[1]/form#login"].unit_id
    assert by_symbol["div[1]/form#login"].parent_unit_id is None
    assert len(full) > len(meaningful)


@readable(
    intention="Keep only top-level CSS statements.",
    steps=["Extract a stylesheet with nested media rules and keyframes using both profiles."],
    criteria=["Nested rules and keyframe steps disappear; top-level statements keep their full-profile symbols."],
)
def test_meaningful_css_keeps_top_level_statements(tmp_path):
    full = {unit.symbol: unit for unit in _units(tmp_path, "css", STYLESHEET, "full")}
    meaningful = _units(tmp_path, "css", STYLESHEET, "meaningful")
    assert {unit.symbol for unit in meaningful} == {".page[1]", "@media (max-width: 600px)[1]", "@keyframes spin[1]"}
    assert all(unit.symbol in full for unit in meaningful)
    assert not any(unit.symbol_type == "css_keyframe" for unit in meaningful)


def test_unknown_markup_granularity_is_rejected():
    assert normalize_markup_granularity(None) == "full"
    with pytest.raises(ValueError):
        normalize_markup_granularity("tiny")


@readable(
    intention="Store updates as field-level, compressed change records that remain readable.",
    steps=["Build a field-level change and encode small and large payloads."],
    criteria=["Only identity and changed keys remain; small payloads stay JSON text; large ones are compressed; "
              "legacy JSON text still decodes."],
)
def test_change_records_are_field_level_and_compressed():
    old = {"id": "a", "uid": "u", "purpose": "old", "code": {"path": "x.py"}, "notes": "gone"}
    new = {"id": "a", "uid": "u", "purpose": "new", "code": {"path": "x.py"}}
    before, after = field_level_change(old, new)
    assert before == {PARTIAL_MARKER: True, "id": "a", "uid": "u", "purpose": "old", "notes": "gone"}
    assert after == {PARTIAL_MARKER: True, "id": "a", "uid": "u", "purpose": "new", "$absent": ["notes"]}
    assert isinstance(encode_delta_payload({"small": 1}), str)
    large = {"text": "x" * 1000}
    encoded = encode_delta_payload(large)
    assert isinstance(encoded, bytes) and decode_delta_payload(encoded) == large
    assert decode_delta_payload(json.dumps(large)) == large


def _markup_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "page.html").write_text(TEMPLATE, encoding="utf-8")
    full_units, _ = extract_units("html", root / "src" / "page.html", Path("src/page.html"))
    blocks = [
        {"id": f"block_{index}", "uid": f"bp_{index}", "domain": "web", "status": "active",
         "purpose": f"Render the html element '{unit.symbol}' declared in 'src/page.html'.",
         "code": {"path": unit.path, "symbol": unit.symbol, "kind": unit.symbol_type}}
        for index, unit in enumerate(full_units)
    ]
    data = {"version": 1, "project": {"name": "sample", "source_roots": ["src"]}, "blocks": blocks}
    blueprint = root / ".bpfw" / "blueprint.yaml"
    blueprint.parent.mkdir(parents=True)
    blueprint.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert migrate_legacy(root, apply=True)["activated"]
    return root


@readable(
    intention="Regranulate an authority without logging untouched blocks as changed.",
    steps=["Preview and apply the meaningful profile on a migrated project, then read the change records."],
    criteria=["Only wrapper blocks are removed; the profile is recorded; shifted blocks produce one reorder record "
              "instead of full upserts; the document order matches the new positions."],
)
def test_regranulate_removes_wrappers_with_compact_records(tmp_path):
    root = _markup_project(tmp_path)
    store = SqliteAuthorityStore(root)
    plan = plan_regranulation(root, store, "meaningful")
    assert plan["removable_blocks"] == plan["markup_units_current"] - plan["markup_units_target"] > 0
    assert plan["removable_purposes"]["custom"] == 0
    result = apply_regranulation(root, store, plan)
    assert result["removed_blocks"] == plan["removable_blocks"]
    document = store.load_document()
    assert document["project"]["markup_granularity"] == "meaningful"
    assert len(document["blocks"]) == plan["markup_units_target"]
    with sqlite3.connect(store.path) as connection:
        kinds = [row[0] for row in connection.execute(
            "SELECT kind FROM operation_deltas d JOIN operation_log l USING(operation_id) "
            "WHERE l.result_revision=?", (result["revision"],))]
        orders = [row[0] for row in connection.execute("SELECT display_order FROM blocks ORDER BY display_order")]
    assert "block.upsert" not in kinds and kinds.count("blocks.reorder") <= 1
    assert orders == list(range(len(orders)))
    assert plan_regranulation(root, store, "meaningful")["removable_blocks"] == 0


@readable(
    intention="Compact the authority losslessly and shrink only records already kept by the history ledger.",
    steps=["Make a full-block update, compact before and after projecting the outbox."],
    criteria=["Pending operations keep full records; projected ones become field-level; doctor stays healthy."],
)
def test_authority_compaction_respects_pending_history(tmp_path):
    root = _markup_project(tmp_path)
    store = SqliteAuthorityStore(root)
    document = store.load_document()
    document["blocks"][0]["purpose"] = "Lay out the page."
    store.replace_document(document, reason="edit")
    plan = plan_compaction(store, keep_operations=0)
    assert plan["prunable_operations"] == 0
    apply_compaction(root, store, keep_operations=5)
    with sqlite3.connect(store.path) as connection:
        before_raw = connection.execute(
            "SELECT before_json FROM operation_deltas WHERE kind='block.upsert'").fetchone()[0]
    assert decode_delta_payload(before_raw).get(PARTIAL_MARKER) is True
    project_outbox(root, limit=100)
    result = apply_compaction(root, store, keep_operations=0)
    assert result["pruned_operations"] >= 1
    assert store.doctor()["ok"]


@readable(
    intention="Rewrite an old history ledger compactly without losing events or objects.",
    steps=["Write two legacy plain batches sharing one object, then compact the ledger."],
    criteria=["Archives become gzip, the shared object is stored once, and every event and object is readable."],
)
def test_history_compaction_is_lossless(tmp_path):
    ledger = HistoryLedger(tmp_path)
    shared = {"kind": "shared", "payload": "y" * 500}
    digest_ref = None
    for number in range(2):
        with ledger.batch():
            digest_ref = ledger.store_object(shared)
            ledger.append({"event_id": f"event_{number}", "event_type": "TEST", "git": {},
                           "change": {"after": digest_ref}})
    for path in _history_files(ledger.events_root):
        payload = _read_history_file(path)
        payload["objects"] = {digest_ref.split(":", 1)[1]: shared}
        legacy = path.with_name(path.name.replace(".json.gz", ".json"))
        legacy.write_text(json.dumps(payload), encoding="utf-8")
        path.unlink()
    result = apply_history_compaction(tmp_path)
    archives = _history_files(ledger.events_root)
    assert all(path.name.endswith(".json.gz") for path in archives)
    assert result["dropped_duplicate_objects"] == 1
    assert {event["event_id"] for event in ledger.query(limit=10)} == {"event_0", "event_1"}
    assert ledger.read_object(digest_ref) == shared
