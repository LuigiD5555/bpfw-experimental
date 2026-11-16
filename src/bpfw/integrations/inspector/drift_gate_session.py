"""Persistent decision-session state for Drift Gate.

The session owns decision records and pending-item persistence, but deliberately
has no terminal input/output and performs no authority mutation.  This keeps
human interaction separate from resumable state semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from bpfw.integrations.diff.models import DiffItem
from bpfw.integrations.inspector.base import InspectIssue
from bpfw.integrations.inspector.drift_gate_helpers import diff_item_touches_paths
from bpfw.integrations.inspector.drift_state import (
    DriftDecisionRecord,
    DriftState,
    DriftStateRepository,
)


@dataclass(frozen=True, slots=True)
class CachedDecisionEffect:
    """Result impact of reusing one persisted Drift Gate decision."""

    reusable: bool
    approved: int = 0
    attached: int = 0
    ignored: int = 0
    rejected: int = 0
    reused: int = 0
    issue: InspectIssue | None = None


class DriftDecisionSession:
    """Manage resumable Drift Gate decision state without terminal concerns."""

    def __init__(
        self,
        repository: DriftStateRepository,
        state: DriftState,
        input_signature: str | None,
    ) -> None:
        self.repository = repository
        self.state = state
        self.input_signature = input_signature
        self.active_items: list[DiffItem] = []

    def begin(self, items: list[DiffItem]) -> None:
        """Start or replace the active human-decision set and persist it."""
        self.active_items = list(items)
        self.state.replace_pending_items(self.active_items)
        self.save(pending_human_decisions=len(self.active_items))

    def replace_pending(self, items: list[DiffItem]) -> None:
        """Persist a known remaining review queue."""
        self.state.replace_pending_items(list(items))
        self.save(pending_human_decisions=len(items))

    def finish(self, *, unresolved_count: int = 0) -> None:
        """Finish the active review while preserving explicit unresolved count."""
        self.state.replace_pending_items([])
        self.save(pending_human_decisions=max(unresolved_count, 0))
        self.active_items = []

    def record_decision(
        self,
        item: DiffItem,
        status: str,
        decision: str,
        reason: str | None = None,
        issue: InspectIssue | None = None,
    ) -> None:
        """Record one decision and immediately persist remaining work."""
        self.state.record_decision(
            item=item,
            status=status,
            decision=decision,
            reason=reason,
            issue=issue,
        )
        self.save_current_progress()

    def pending_items(self) -> list[DiffItem]:
        """Return active items without a decision matching current evidence."""
        return [
            item
            for item in self.active_items
            if self.state.current_record_for(item) is None
        ]

    def save_current_progress(self) -> None:
        """Persist recorded decisions plus active unresolved items."""
        remaining_items = self.pending_items()
        self.state.replace_pending_items(remaining_items)
        self.save(pending_human_decisions=len(remaining_items))

    def save(self, *, pending_human_decisions: int) -> None:
        """Persist the current DriftState with a normalized timestamp/signature."""
        self.state.input_signature = self.input_signature
        self.state.pending_human_decisions = max(pending_human_decisions, 0)
        self.state.last_analyzed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        self.repository.save(self.state)

    def current_reusable_record(self, item: DiffItem) -> DriftDecisionRecord | None:
        """Return reusable record unless file-level invalidation touches the item."""
        invalidated_paths = set(
            self.state.changed_paths + self.state.added_paths + self.state.removed_paths
        )
        if invalidated_paths and diff_item_touches_paths(item=item, paths=invalidated_paths):
            return None
        return self.state.current_record_for(item)

    @staticmethod
    def cached_effect(record: DriftDecisionRecord) -> CachedDecisionEffect:
        """Translate a current decision record into runner result effects."""
        if record.status == "approved_for_inspector":
            issue = record.to_inspect_issue()
            if issue is None:
                return CachedDecisionEffect(reusable=False)
            return CachedDecisionEffect(reusable=True, approved=1, reused=1, issue=issue)
        if record.status == "attached":
            return CachedDecisionEffect(reusable=True, attached=1, reused=1)
        if record.status == "ignored":
            return CachedDecisionEffect(reusable=True, ignored=1, reused=1)
        if record.status in {"rejected", "source_delete_marked"}:
            return CachedDecisionEffect(reusable=True, rejected=1, reused=1)
        if record.status in {"resolved", "deferred"}:
            return CachedDecisionEffect(reusable=True, reused=1)
        return CachedDecisionEffect(reusable=False)
