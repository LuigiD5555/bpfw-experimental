from pathlib import Path

from bpfw.integrations.inspector.base import (
    ISSUE_DRAFT,
    InspectIssue,
    has_uninspectable_source_issues,
    split_issues_by_source_availability,
)


def _build_issue(source_path: str) -> InspectIssue:
    """Build an inspector issue pointing to a source file path."""

    return InspectIssue(
        issue_type=ISSUE_DRAFT,
        block={
            "id": source_path.replace("/", "_"),
            "purpose": None,
            "name": "Example",
            "domain": "example",
            "status": "active",
            "code": {
                "path": source_path,
                "symbol": "Example",
                "kind": "class",
                "start_line": 1,
                "end_line": 1,
            },
        },
    )


def test_split_issues_by_source_availability_keeps_only_existing_sources(tmp_path: Path) -> None:
    """Verify stale metadata issues are separated from inspectable issues."""

    existing_source = tmp_path / "src" / "example.py"
    existing_source.parent.mkdir(parents=True)
    existing_source.write_text("class Example:\n    pass\n", encoding="utf-8")

    inspectable_issue = _build_issue("src/example.py")
    stale_issue = _build_issue("src/missing.py")

    inspectable_issues, stale_issues = split_issues_by_source_availability(
        project_root=tmp_path,
        issues=[inspectable_issue, stale_issue],
    )

    assert inspectable_issues == [inspectable_issue]
    assert stale_issues == [stale_issue]


def test_has_uninspectable_source_issues_detects_missing_source(tmp_path: Path) -> None:
    """Verify metadata queues with missing source files are rejected."""

    assert has_uninspectable_source_issues(
        project_root=tmp_path,
        issues=[_build_issue("src/missing.py")],
    )

from bpfw.integrations.inspector.drift_gate import DriftGateResult
from bpfw.integrations.inspector.session import _should_block_on_stale_metadata_queue


def test_stale_metadata_blocks_only_when_resuming_from_cache() -> None:
    """Verify stale cached metadata blocks only before fresh Drift Gate reconciliation."""

    cached_result = DriftGateResult(cache_hit=True)
    assert _should_block_on_stale_metadata_queue(cached_result)

    fresh_result = DriftGateResult(cache_hit=False)
    assert not _should_block_on_stale_metadata_queue(fresh_result)

    changed_result = DriftGateResult(cache_hit=True)
    changed_result.changed_authority_count = 1
    assert not _should_block_on_stale_metadata_queue(changed_result)

    reviewed_cached_pending_result = DriftGateResult(cache_hit=True)
    reviewed_cached_pending_result.reviewed_human_item_count = 321
    assert not _should_block_on_stale_metadata_queue(reviewed_cached_pending_result)


def test_stale_metadata_does_not_block_approved_resume() -> None:
    """Verify stale drafts are discarded when approved Inspector work exists."""

    approved_result = DriftGateResult(cache_hit=True)
    approved_result.approved_count = 1

    assert not _should_block_on_stale_metadata_queue(approved_result)
