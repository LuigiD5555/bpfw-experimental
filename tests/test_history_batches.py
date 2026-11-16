"""Durable history batches retain legacy events, content addressing and index recovery."""

import json
import sqlite3
from unittest.mock import patch

import pytest
from pytest_readable import readable

from bpfw.core.history.ledger import (
    HistoryLedger,
    _history_files,
    _read_history_file,
    capture_artifact_state,
)


@readable(
    intention="Rebuild complete history from individual events and durable batches.",
    steps=["Write a legacy event and a batch containing two events and content objects, then rebuild the index."],
    criteria=["All event IDs and both old and new object references remain readable; secret fields stay redacted."],
)
def test_batch_and_legacy_history_rebuild_together(tmp_path):
    ledger = HistoryLedger(tmp_path)
    legacy_reference = ledger.store_object({"kind": "legacy"})
    ledger.append({"event_id": "legacy", "event_type": "LEGACY", "git": {},
                   "change": {"after": legacy_reference, "password": "example-legacy-test-value"}})
    with ledger.batch():
        reference = ledger.store_object({"password": "example-test-value", "kind": "batch"})
        ledger.append({"event_id": "first", "event_type": "FIRST", "git": {}, "change": {"after": reference}})
        ledger.append({"event_id": "second", "event_type": "SECOND", "git": {}})
    archives = _history_files(ledger.events_root)
    assert "example-legacy-test-value" not in json.dumps(ledger.query(limit=10))
    assert len(archives) == 2
    batch = next(_read_history_file(path) for path in archives if path.name.startswith("batch_"))
    assert len(batch["events"]) == 2 and len(batch["objects"]) == 1
    ledger.rebuild_index()
    assert {event["event_id"] for event in ledger.query(limit=10)} == {"legacy", "first", "second"}
    assert ledger.read_object(legacy_reference) == {"kind": "legacy"}
    assert ledger.read_object(reference)["password"]["redacted"] is True
    assert "example-test-value" not in json.dumps(batch)


@readable(
    intention="Discard a batch that fails before its durable commit.",
    steps=["Raise during a batch after staging an object and event, then append a normal event."],
    criteria=["No staged event or object is archived, and later history remains usable."],
)
def test_failed_batch_does_not_publish_partial_events(tmp_path):
    ledger = HistoryLedger(tmp_path)
    with pytest.raises(RuntimeError, match="abort"):
        with ledger.batch():
            ledger.store_object({"kind": "uncommitted"})
            ledger.append({"event_id": "uncommitted", "git": {}})
            raise RuntimeError("abort")
    assert not ledger.events_root.exists()
    ledger.append({"event_id": "committed", "event_type": "COMMITTED", "git": {}})
    assert [event["event_id"] for event in ledger.query()] == ["committed"]


@readable(
    intention="Recover a durable batch when its derived index write fails.",
    steps=["Fail the index write after the archive commits, then rebuild the index."],
    criteria=["The archived event and its content object remain recoverable."],
)
def test_durable_batch_survives_index_failure(tmp_path):
    ledger = HistoryLedger(tmp_path)
    with patch.object(ledger, "_index_events", side_effect=sqlite3.OperationalError("index unavailable")):
        with pytest.raises(sqlite3.OperationalError):
            with ledger.batch():
                reference = ledger.store_object({"kind": "recoverable"})
                ledger.append({"event_id": "recoverable", "event_type": "RECOVERABLE", "git": {},
                               "change": {"after": reference}})
    assert len(_history_files(ledger.events_root)) == 1
    ledger.rebuild_index()
    assert [event["event_id"] for event in ledger.query()] == ["recoverable"]
    assert ledger.read_object(reference) == {"kind": "recoverable"}


@readable(
    intention="Capture many artifacts using bounded durable writes.",
    steps=["Capture a file containing many independent functions and query its persisted history."],
    criteria=["Every artifact has an event and readable state while archive writes do not grow per artifact."],
)
def test_artifact_capture_uses_one_durable_batch(tmp_path):
    (tmp_path / "sample.py").write_text("".join(
        f"def function_{number}():\n    return {number}\n" for number in range(100)
    ))
    blueprint = {"blocks": [
        {"id": f"block_{number}", "code": {"path": "sample.py", "symbol": f"function_{number}", "kind": "function"}}
        for number in range(100)
    ]}
    with patch.object(HistoryLedger, "git_context", return_value={}):
        events = capture_artifact_state(tmp_path, blueprint)
    ledger = HistoryLedger(tmp_path)
    assert len(events) == 100
    assert len(_history_files(ledger.events_root)) == 2
    assert len(ledger.query(event_type="ARTIFACT_BASELINE", limit=200)) == 100
    assert all(ledger.read_object(event["change"]["after"])["resolution"] == "EXACT" for event in events)
