"""Runtime snapshot formatting helpers."""

from __future__ import annotations

import json

from bpfw.runtime.contract import RuntimeSnapshotDocument



def snapshot_to_dict(snapshot: RuntimeSnapshotDocument) -> dict:
    """Serialize runtime snapshot to dictionary."""

    return {
        "active_bindings": [
            {
                "responsibility_id": binding.responsibility_id,
                "declared_active_implementation": binding.declared_active_implementation,
                "runtime_implementation": binding.runtime_implementation,
                "source": binding.source,
            }
            for binding in snapshot.active_bindings
        ]
    }



def snapshot_to_json(snapshot: RuntimeSnapshotDocument) -> str:
    """Serialize runtime snapshot to JSON string."""

    return json.dumps(snapshot_to_dict(snapshot), indent=2)



def snapshot_to_human_lines(snapshot: RuntimeSnapshotDocument) -> str:
    """Build readable multi-line snapshot output for CLI."""

    if not snapshot.active_bindings:
        return "(no active bindings)"

    lines: list[str] = []
    for binding in snapshot.active_bindings:
        runtime_value = binding.runtime_implementation or "<undetected>"
        lines.append(
            (
                f"- {binding.responsibility_id}: declared={binding.declared_active_implementation}, "
                f"runtime={runtime_value}, source={binding.source}"
            )
        )
    return "\n".join(lines)
