"""Shared data models for the Drift Gate workflow.

Keeping these models outside the interactive runner lets decision/session and
undo logic depend on stable data structures without importing terminal code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bpfw.integrations.inspector.base import InspectIssue


@dataclass(slots=True)
class DriftGateResult:
    """Result produced by a Drift Gate pass."""

    safe_mechanical_updates: int = 0
    approved_count: int = 0
    ignored_count: int = 0
    rejected_count: int = 0
    skipped_count: int = 0
    attached_count: int = 0
    changed_authority_count: int = 0
    reused_decision_count: int = 0
    reviewed_human_item_count: int = 0
    cache_hit: bool = False
    inspector_issues: list[InspectIssue] = field(default_factory=list)
    stopped: bool = False
    exit_code: int = 0

    def changed_project_state(self) -> bool:
        """Return whether authority files were changed and should be reloaded."""
        return self.safe_mechanical_updates > 0 or self.changed_authority_count > 0

    def build_context_lines(self) -> list[str]:
        """Build inspector context lines for decisions made before metadata editing."""
        lines: list[str] = []
        if self.safe_mechanical_updates:
            noun = "update" if self.safe_mechanical_updates == 1 else "updates"
            lines.append(
                f"Auto-sync: {self.safe_mechanical_updates} safe mechanical {noun} applied before inspection."
            )
        else:
            lines.append("Auto-sync: no safe mechanical updates were needed.")

        decision_parts: list[str] = []
        if self.approved_count:
            decision_parts.append(f"{self.approved_count} approved for metadata")
        if self.attached_count:
            decision_parts.append(f"{self.attached_count} attached")
        if self.ignored_count:
            decision_parts.append(f"{self.ignored_count} ignored")
        if self.rejected_count:
            decision_parts.append(f"{self.rejected_count} rejected")
        if self.skipped_count:
            decision_parts.append(f"{self.skipped_count} skipped and still unresolved")
        if self.reused_decision_count:
            noun = "decision" if self.reused_decision_count == 1 else "decisions"
            lines.append(f"Drift state: reused {self.reused_decision_count} previous {noun}.")
        if self.cache_hit:
            lines.append("Drift state: unchanged since last inspection.")
        if decision_parts:
            lines.append(f"Drift decisions: {', '.join(decision_parts)}.")
            if self.approved_count:
                lines.append(
                    "Approved for metadata are queued for Inspector; they are saved only when you confirm each item."
                )
        elif self.safe_mechanical_updates or self.cache_hit:
            lines.append("No human drift decisions were required.")
        return lines
