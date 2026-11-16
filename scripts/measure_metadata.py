#!/usr/bin/env python3
"""Measure how much BPFW metadata a project carries, read-only.

Usage:
    python scripts/measure_metadata.py --project-root PATH [--json]

Reports block counts by kind, the SQLite authority size per component, the history ledger size per component
and the size of a compact JSON export of the authority document. Nothing is written; the authority and the
history index are opened read-only and the outbox is not projected.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path


def _read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _payload_bytes(connection: sqlite3.Connection, table: str, columns: list[str]) -> int:
    total = 0
    for row in connection.execute(f"SELECT {', '.join(columns)} FROM {table}"):
        for value in row:
            if isinstance(value, str):
                total += len(value.encode("utf-8"))
            elif isinstance(value, (bytes, bytearray)):
                total += len(value)
    return total


def _tree_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file()) if root.exists() else 0


def measure(project_root: Path) -> dict:
    bpfw = project_root / ".bpfw"
    result: dict = {"project_root": str(project_root)}
    authority = bpfw / "authority.sqlite"
    if authority.is_file():
        with _read_only(authority) as connection:
            kinds: Counter = Counter()
            export_bytes = 0
            for (raw,) in connection.execute("SELECT raw_json FROM blocks"):
                block = json.loads(raw)
                kinds[str((block.get("code") or {}).get("kind") or block.get("kind"))] += 1
                export_bytes += len(raw.encode("utf-8"))
            result["blocks"] = {"total": sum(kinds.values()), "by_kind": dict(kinds.most_common())}
            result["authority"] = {
                "file_bytes": authority.stat().st_size,
                "block_json_bytes": export_bytes,
                "change_record_bytes": _payload_bytes(connection, "operation_deltas", ["before_json", "after_json"]),
                "change_records": connection.execute("SELECT COUNT(*) FROM operation_deltas").fetchone()[0],
                "operations": connection.execute("SELECT COUNT(*) FROM operation_log").fetchone()[0],
                "pending_outbox": connection.execute(
                    "SELECT COUNT(*) FROM outbox_events WHERE published_at IS NULL").fetchone()[0],
            }
    history = bpfw / "history"
    index = history / "index.sqlite"
    result["history"] = {
        "events_bytes": _tree_bytes(history / "events"),
        "objects_bytes": _tree_bytes(history / "objects"),
        "index_bytes": sum(path.stat().st_size for path in history.glob("index.sqlite*") if path.is_file()),
        "artifact_state_bytes": (history / "artifact-state.json").stat().st_size
        if (history / "artifact-state.json").exists() else 0,
    }
    if index.is_file():
        with _read_only(index) as connection:
            result["history"]["indexed_events"] = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            result["history"]["indexed_objects"] = connection.execute("SELECT COUNT(*) FROM object_blobs").fetchone()[0]
    result["history"]["total_bytes"] = sum(
        value for key, value in result["history"].items() if key.endswith("_bytes"))
    result["bpfw_total_bytes"] = _tree_bytes(bpfw)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(argv)
    result = measure(options.project_root.resolve())
    if options.json:
        print(json.dumps(result, indent=2))
        return 0
    mib = lambda value: f"{value / 1048576:8.1f} MiB"  # noqa: E731
    print(f"blocks: {result.get('blocks', {}).get('total')}  {result.get('blocks', {}).get('by_kind')}")
    for section in ("authority", "history"):
        for key, value in result.get(section, {}).items():
            print(f"{section:9} {key:22} {mib(value) if key.endswith('bytes') else value}")
    print(f"total     .bpfw                  {mib(result['bpfw_total_bytes'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
