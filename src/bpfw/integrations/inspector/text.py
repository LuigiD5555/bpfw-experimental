"""Compatibility facade for the text inspector integration.

This module is kept for backward compatibility. New code should use
bpfw.integrations.inspector.run_text_inspector directly.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from bpfw.catalog.schema import get_blocks, get_code
from bpfw.integrations.inspector.base import InspectIssue, clean_string, load_inspect_session
from bpfw.integrations.inspector.screen import render_inspector_screen
from bpfw.integrations.inspector.session import (
    run_text_inspector,
    run_text_inspector_session,
)

DEFAULT_INSPECTOR_TITLE = "Blueprint Framework Inspector"
InputFunc = Callable[[str], str]
PrintFunc = Callable[[str], None]

# Backward compatibility aliases
render_text_inspector_screen = render_inspector_screen


def run_inspector_target(
    project_root: Path,
    responsibility_id: str,
    header_title: str = DEFAULT_INSPECTOR_TITLE,
    input_func: InputFunc = input,
    print_func: PrintFunc = print,
) -> str:
    """Open inspector focused on one block in target mode."""

    session = load_inspect_session(project_root=project_root)
    if session.blocked:
        print_func(session.message or "Inspector blocked.")
        return "error"

    target_index = _find_issue_index(session.issues, responsibility_id)

    if target_index is None:
        block = _find_responsibility_in_blueprint(session.blueprint_data, responsibility_id)
        if block is None:
            print_func(f"Block not found: {responsibility_id}")
            return "error"

        synthetic_issue = InspectIssue(
            issue_type="target",
            block=block,
            add_on_accept=False,
        )
        session.issues = [synthetic_issue]
        target_index = 0

    session.issues = [session.issues[target_index]]

    print_func("")
    print_func("Opening in Inspector...")
    print_func("")

    block = session.issues[0].block
    location_data = get_code(block)
    if isinstance(location_data, dict):
        location_path = clean_string(location_data.get("path")) or "unknown"
        location_symbol = clean_string(location_data.get("symbol")) or "unknown"
        print_func(f"  {block.get('name', block.get('canonical_name', 'unknown'))}")
        print_func(f"  {location_path} :: {location_symbol}")
    print_func("")

    run_text_inspector_session(
        session=session,
        header_title=header_title,
        input_func=input_func,
        print_func=print_func,
    )
    return "saved"


def _find_issue_index(issues: list[InspectIssue], responsibility_id: str) -> int | None:
    """Find the index of an issue matching the block ID."""

    for index, issue in enumerate(issues):
        issue_id = issue.block.get("id", "")
        if issue_id == responsibility_id:
            return index
    return None


def _find_responsibility_in_blueprint(
    blueprint_data: dict[str, Any],
    responsibility_id: str,
) -> dict[str, Any] | None:
    """Find a block in blueprint data by ID."""

    blocks = get_blocks(blueprint_data)

    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("id") == responsibility_id:
            return block
    return None

__all__ = [
    "run_text_inspector",
    "run_text_inspector_session",
    "render_text_inspector_screen",
    "run_inspector_target",
]