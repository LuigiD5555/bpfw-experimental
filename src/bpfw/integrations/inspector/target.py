"""Targeted inspector entrypoint for opening one blueprint block."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from bpfw.catalog.schema import get_blocks, get_code
from bpfw.integrations.inspector.base import InspectIssue, clean_string, load_inspect_session
from bpfw.integrations.inspector.session import run_text_inspector_session

DEFAULT_INSPECTOR_TITLE = "Blueprint Framework Inspector"
InputFunc = Callable[[str], str]
PrintFunc = Callable[[str], None]


def run_inspector_target(
    project_root: Path,
    block_id: str,
    header_title: str = DEFAULT_INSPECTOR_TITLE,
    input_func: InputFunc = input,
    print_func: PrintFunc = print,
) -> str:
    """Open the inspector focused on one block in target mode.

    Args:
        project_root: Root directory of the project being inspected.
        block_id: Identifier of the block that should be opened.
        header_title: Title rendered by the inspector screen.
        input_func: Callable used to collect terminal input.
        print_func: Callable used to print terminal output.

    Returns:
        The result string returned by the target inspector flow.
    """

    session = load_inspect_session(project_root=project_root)
    if session.blocked:
        print_func(session.message or "Inspector blocked.")
        return "error"

    target_index = _find_issue_index(session.issues, block_id)

    if target_index is None:
        block = _find_block_in_blueprint(session.blueprint_data, block_id)
        if block is None:
            print_func(f"Block not found: {block_id}")
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
    code_data = get_code(block)
    if isinstance(code_data, dict):
        code_path = clean_string(code_data.get("path")) or "unknown"
        code_symbol = clean_string(code_data.get("symbol")) or "unknown"
        print_func(f"  {block.get('name', block.get('canonical_name', 'unknown'))}")
        print_func(f"  {code_path} :: {code_symbol}")
    print_func("")

    run_text_inspector_session(
        session=session,
        header_title=header_title,
        input_func=input_func,
        print_func=print_func,
    )
    return "saved"


def _find_issue_index(issues: list[InspectIssue], block_id: str) -> int | None:
    """Find the index of an issue matching the block identifier.

    Args:
        issues: Inspector issues currently available in the session.
        block_id: Identifier of the target block.

    Returns:
        The matching issue index, or None when no issue matches.
    """

    for index, issue in enumerate(issues):
        issue_id = issue.block.get("id", "")
        if issue_id == block_id:
            return index
    return None


def _find_block_in_blueprint(
    blueprint_data: dict[str, Any],
    block_id: str,
) -> dict[str, Any] | None:
    """Find a block in blueprint data by identifier.

    Args:
        blueprint_data: Parsed blueprint data.
        block_id: Identifier of the target block.

    Returns:
        The matching block dictionary, or None when no block matches.
    """

    blocks = get_blocks(blueprint_data)

    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("id") == block_id:
            return block
    return None
