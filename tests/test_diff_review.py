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

