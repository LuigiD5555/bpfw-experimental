"""Pure helpers shared by the Inspector Drift Gate.

These functions intentionally contain no authority writes or interactive state.
Keeping them separate makes the large Drift Gate workflow easier to characterize
and refactor without changing its decision semantics.
"""
from __future__ import annotations

from textwrap import wrap
from typing import Any

from bpfw.integrations.diff.models import BlueprintTarget, CodeTarget, DiffItem
from bpfw.integrations.inspector.base import InspectIssue, clean_string
from bpfw.shared.text import to_snake_case

DRIFT_GATE_WIDTH = 80
BOX_INNER_WIDTH = DRIFT_GATE_WIDTH - 4


def inspect_issue_code_key(issue: InspectIssue) -> tuple[str, str, str] | None:
    """Return the code target key for an inspector issue."""
    code_data = issue.block.get("code")
    if not isinstance(code_data, dict):
        return None
    path = clean_string(code_data.get("path"))
    symbol = clean_string(code_data.get("symbol"))
    kind = clean_string(code_data.get("kind"))
    if path is None or symbol is None or kind is None:
        return None
    return path, symbol, kind


def has_meaningful_context(result: Any) -> bool:
    """Return whether a Drift Gate result contains an action worth explaining."""
    return any(
        value > 0
        for value in (
            result.safe_mechanical_updates,
            result.approved_count,
            result.ignored_count,
            result.rejected_count,
            result.skipped_count,
            result.attached_count,
        )
    )


def block_from_code_target(code: CodeTarget) -> dict[str, Any]:
    """Build the legacy minimal authority block for a discovered code target."""
    return {
        "id": to_snake_case(code.symbol),
        "purpose": None,
        "domain": None,
        "status": "experimental",
        "code": {
            "path": code.path,
            "symbol": code.symbol,
            "kind": code.kind,
            "start_line": code.start_line,
            "end_line": code.end_line,
        },
        "detected": {
            "qualified_name": code.qualified_name,
            "kind": code.kind,
            "methods": [],
            "functions": [],
        },
        "entrypoints": [],
        "connections": [],
        "uniqueness": {
            "group": None,
            "allow_multiple_non_active": True,
            "forbid_active_duplicates": True,
            "suspected_duplicates": [],
        },
        "replacement": {
            "replaces": None,
            "replaced_by": None,
            "reason": None,
        },
        "notes": None,
    }


def target_location(target: BlueprintTarget | None) -> str:
    """Return a compact authority location for Drift Gate rendering."""
    if target is None:
        return "unavailable"
    if target.path and target.symbol:
        return f"{target.path}::{target.symbol}"
    return target.block_id


def target_block_id(target: BlueprintTarget | None) -> str:
    """Return the authority block identifier or a placeholder."""
    if target is None:
        return "unavailable"
    return target.block_id


def wrap_operation_box_text(text: str) -> list[str]:
    """Wrap one operation-box text line without changing meaning content."""
    if len(text) <= BOX_INNER_WIDTH:
        return [text]
    indent = text[: len(text) - len(text.lstrip(" "))]
    wrapped_lines = wrap(
        text,
        width=BOX_INNER_WIDTH,
        initial_indent="",
        subsequent_indent=indent,
        break_long_words=True,
        break_on_hyphens=False,
    )
    return wrapped_lines or [text[:BOX_INNER_WIDTH]]


def diff_item_touches_paths(item: DiffItem, paths: set[str]) -> bool:
    """Return whether a diff item references any changed path."""
    touched_paths: set[str] = set()
    if item.code_target is not None and item.code_target.path:
        touched_paths.add(item.code_target.path)
    for candidate in item.candidates:
        if candidate.path:
            touched_paths.add(candidate.path)
    if item.finding is not None and item.finding.path:
        touched_paths.add(item.finding.path)
    if item.blueprint_target is not None and item.blueprint_target.path:
        touched_paths.add(item.blueprint_target.path)
    return any(path in paths for path in touched_paths)
