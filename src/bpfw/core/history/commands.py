"""Human-readable history, why, and source trace queries."""
from __future__ import annotations
from pathlib import Path
from typing import Any

from bpfw.core.artifacts import ArtifactResolver, block_artifacts
from bpfw.core.catalog.loader import BlueprintLoader
from bpfw.core.history.ledger import HistoryLedger


def _entity_label(event: dict[str, Any]) -> str:
    e = event.get("entity") if isinstance(event.get("entity"), dict) else {}
    return str(e.get("id_at_event") or e.get("id") or e.get("uid") or "-")


def render_events(events: list[dict[str, Any]], *, title: str = "BPFW HISTORY") -> str:
    lines = [title]
    if not events:
        return title + "\n  No matching history events."
    for event in events:
        stamp = str(event.get("timestamp") or "-")
        stamp = stamp.replace("T", " ")[:19]
        etype = str(event.get("event_type") or "-")
        entity = _entity_label(event)
        location = event.get("location") if isinstance(event.get("location"), dict) else {}
        place = str(location.get("path") or "")
        if location.get("symbol"): place += f"::{location['symbol']}"
        reason = event.get("reason")
        if isinstance(reason, dict): reason = reason.get("summary") or reason.get("details")
        lines.append(f"  {stamp}  {etype:<28} {entity}")
        if place: lines.append(f"    source: {place}")
        if reason: lines.append(f"    why:    {reason}")
        lines.append(f"    event:  {event.get('event_id', '-')}")
    return "\n".join(lines)


def trace_location(project_root: Path, target: str) -> dict[str, Any]:
    if ":" not in target:
        return {"error": "Trace target must be PATH:LINE"}
    path_text, line_text = target.rsplit(":", 1)
    try: line = int(line_text)
    except ValueError: return {"error": "Trace line must be an integer"}
    load = BlueprintLoader(project_root=project_root).load()
    resolver = ArtifactResolver(project_root)
    matches = []
    blocks = load.data.get("blocks", []) if isinstance(load.data, dict) else []
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict): continue
        for artifact in block_artifacts(block):
            if str(artifact.get("path") or "").replace("\\", "/") != path_text.replace("\\", "/"):
                continue
            resolved = resolver.resolve(artifact)
            if resolved.resolved and int(resolved.start_line) <= line <= int(resolved.end_line):
                matches.append({
                    "block_id": block.get("id"), "block_uid": block.get("uid"),
                    "artifact_id": artifact.get("id") or resolved.artifact_id, "artifact_uid": artifact.get("uid"),
                    "path": resolved.path, "symbol": resolved.symbol, "kind": resolved.kind,
                    "start_line": resolved.start_line, "end_line": resolved.end_line,
                })
    ledger = HistoryLedger(project_root)
    events = ledger.query(path_text, limit=50)
    return {"target": target, "matches": matches, "events": events}


def render_trace(result: dict[str, Any]) -> str:
    if result.get("error"): return "BPFW TRACE\n  " + str(result["error"])
    lines = ["BPFW TRACE", f"  target: {result.get('target')}"]
    matches = result.get("matches") or []
    if not matches:
        lines.append("  Current owner: not resolved")
    for item in matches:
        lines.append(f"  owner:    {item.get('block_id')} [{item.get('artifact_id')}]")
        lines.append(f"  source:   {item.get('path')}::{item.get('symbol') or '-'} L{item.get('start_line')}-{item.get('end_line')}")
    events = result.get("events") or []
    if events:
        lines.append("")
        lines.append(render_events(events[:20], title="RELATED HISTORY"))
    return "\n".join(lines)
