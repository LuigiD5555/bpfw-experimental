"""PURPOSE targeted inspector entrypoint for opening one blueprint block
DOMAIN  inspector workflow
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

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
    """PURPOSE open the inspector focused on one block in target mode
    DOMAIN  inspector workflow
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
    code_data = block.get("code", {})
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
    """PURPOSE find the index of an issue matching the block identifier
    DOMAIN  inspector workflow
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
    """PURPOSE find a block in blueprint data by identifier
    DOMAIN  inspector workflow
    """

    blocks = blueprint_data.get("blocks", [])

    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("id") == block_id:
            return block
    return None
