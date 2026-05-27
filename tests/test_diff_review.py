"""Tests for diff finding classification and action levels."""

from bpfw.integrations.diff.models import DiffActionLevel, DiffItemKind
from bpfw.integrations.diff.review import _action_level_for_kind, _map_finding_code


def test_map_incomplete_block_to_incomplete_metadata() -> None:
    """Map incomplete authority metadata to INCOMPLETE_METADATA."""
    assert _map_finding_code("INCOMPLETE_BLOCK") == DiffItemKind.INCOMPLETE_METADATA


def test_map_invalid_status_to_incomplete_metadata() -> None:
    """Map invalid status metadata issues to INCOMPLETE_METADATA."""
    assert _map_finding_code("INVALID_STATUS") == DiffItemKind.INCOMPLETE_METADATA


def test_action_level_for_undeclared_code_is_human_decision() -> None:
    """Undeclared code should require human decision in this phase."""
    assert _action_level_for_kind(DiffItemKind.UNDECLARED_CODE) == DiffActionLevel.HUMAN_DECISION


from bpfw.core.catalog.models import DiscoveredCodeUnit
from bpfw.integrations.diff.models import CodeTarget, DiffItem, DiffRisk
from bpfw.integrations.diff.review import _order_undeclared_items_by_scan_review_order


def test_undeclared_diff_items_follow_scan_review_order() -> None:
    """Approved-new candidates should follow child-before-parent scan order."""
    discovered_units = [
        DiscoveredCodeUnit(
            path="engine.py",
            module="engine",
            symbol="AuthorityPatchEngine.preview",
            symbol_type="method",
            qualified_name="engine.AuthorityPatchEngine.preview",
        ),
        DiscoveredCodeUnit(
            path="engine.py",
            module="engine",
            symbol="AuthorityPatchEngine",
            symbol_type="class",
            qualified_name="engine.AuthorityPatchEngine",
            methods=["engine.AuthorityPatchEngine.preview"],
        ),
    ]
    parent_item = DiffItem(
        identifier="undeclared-code-1",
        kind=DiffItemKind.UNDECLARED_CODE,
        action_level=DiffActionLevel.HUMAN_DECISION,
        risk=DiffRisk.LOW,
        reason="parent",
        code_target=CodeTarget(path="engine.py", symbol="AuthorityPatchEngine", kind="class"),
    )
    child_item = DiffItem(
        identifier="undeclared-code-2",
        kind=DiffItemKind.UNDECLARED_CODE,
        action_level=DiffActionLevel.HUMAN_DECISION,
        risk=DiffRisk.LOW,
        reason="child",
        code_target=CodeTarget(path="engine.py", symbol="AuthorityPatchEngine.preview", kind="method"),
    )

    ordered = _order_undeclared_items_by_scan_review_order(
        [parent_item, child_item],
        discovered_units,
    )

    assert [item.code_target.symbol for item in ordered if item.code_target is not None] == [
        "AuthorityPatchEngine.preview",
        "AuthorityPatchEngine",
    ]
