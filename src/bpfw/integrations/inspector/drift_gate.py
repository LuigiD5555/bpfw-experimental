"""Drift Gate workflow used before inspector metadata editing."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import wrap
from typing import Any

from bpfw.core.authority.patch import PatchWriteContext
from bpfw.core.blueprint_engine import (
    BlueprintChangeKind,
    BlueprintChangeRequest,
    BlueprintChangeSource,
    BlueprintEngine,
    MechanicalChangeEvidence,
)
from bpfw.core.catalog.models import DiscoveredCodeUnit
from bpfw.core.protection.authority import get_authority_protection_status
from bpfw.integrations.diff.models import BlueprintTarget, CodeTarget, DiffItem, DiffItemKind
from bpfw.integrations.diff.package_moves import PackageMoveGroup, group_package_moves
from bpfw.integrations.diff.review import DiffReviewService, DiffReviewSnapshot
from bpfw.integrations.inspector.base import (
    ISSUE_NEW_DETECTED,
    InspectIssue,
    InspectLoadResult,
    build_new_detected_responsibility,
    clean_string,
    get_incomplete_blocks,
)
from bpfw.integrations.inspector.drift_state import (
    DriftDecisionRecord,
    DriftState,
    DriftStateRepository,
)
from bpfw.integrations.shared.cli_runtime import is_quit_command, normalize_command
from bpfw.shared.text import to_snake_case

InputFunc = Callable[[str], str]
PrintFunc = Callable[[str], None]

DRIFT_GATE_WIDTH = 80
BOX_INNER_WIDTH = DRIFT_GATE_WIDTH - 4


@dataclass(slots=True)
class DriftGateResult:
    """Result produced by a Drift Gate pass.

    Attributes:
        safe_mechanical_updates: Number of safe mechanical authority updates applied automatically.
        approved_count: Number of drift decisions approved for metadata inspection.
        ignored_count: Number of code targets deliberately ignored.
        rejected_count: Number of code targets marked as source deletion candidates.
        skipped_count: Number of drift items skipped by the user.
        attached_count: Number of code targets attached to an existing responsibility.
        changed_authority_count: Number of authority changes applied during Drift Gate.
        inspector_issues: Inspector issues created by accepted drift decisions.
        stopped: Whether the user quit Drift Gate before inspection.
        exit_code: Exit code to return when stopped.
    """

    safe_mechanical_updates: int = 0
    approved_count: int = 0
    ignored_count: int = 0
    rejected_count: int = 0
    skipped_count: int = 0
    attached_count: int = 0
    changed_authority_count: int = 0
    reused_decision_count: int = 0
    cache_hit: bool = False
    inspector_issues: list[InspectIssue] = field(default_factory=list)
    stopped: bool = False
    exit_code: int = 0

    def changed_project_state(self) -> bool:
        """Return whether authority files were changed and should be reloaded.

        Returns:
            True when a post-gate reload is useful.
        """
        return self.safe_mechanical_updates > 0 or self.changed_authority_count > 0

    def build_context_lines(self) -> list[str]:
        """Build inspector context lines for decisions made before metadata editing.

        Returns:
            Lines suitable for the inspector pre-inspection context panel.
        """
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
        elif self.safe_mechanical_updates or self.cache_hit:
            lines.append("No human drift decisions were required.")
        return lines


class DriftGateRunner:
    """Run safe auto-sync and human drift decisions before metadata inspection."""

    def __init__(
        self,
        session: InspectLoadResult,
        input_func: InputFunc,
        print_func: PrintFunc,
        cached_human_items: list[DiffItem] | None = None,
        drift_state: DriftState | None = None,
        input_signature: str | None = None,
    ) -> None:
        """Initialize the Drift Gate runner.

        Args:
            session: Loaded inspector session.
            input_func: Function used to read user input.
            print_func: Function used to print terminal output.
            cached_human_items: Optional cached pending human decisions.
            drift_state: Optional preloaded drift state.
            input_signature: Optional precomputed input signature.
        """
        self.session = session
        self.input_func = input_func
        self.print_func = print_func
        self.review_service = DiffReviewService(session.project_root)
        self.blueprint_engine = BlueprintEngine(session.project_root)
        self.state_repository = DriftStateRepository(session.project_root)
        self.drift_state = drift_state if drift_state is not None else self.state_repository.load()
        self.input_signature = input_signature or self.state_repository.build_input_signature()
        self.cached_human_items = list(cached_human_items or [])
        self._active_human_items: list[DiffItem] = []
        self._active_index: int = 0
        self._render_buffer_active = False
        self.result = DriftGateResult()

    def _load_review_snapshot(self) -> DiffReviewSnapshot:
        """Load a diff review snapshot without duplicating work when possible.

        Returns:
            Diff review snapshot.
        """
        if (
            self.session.load_result is not None
            and self.session.verify_report is not None
        ):
            return self.review_service.from_loaded_context(
                load_result=self.session.load_result,
                blueprint_data=self.session.blueprint_data,
                authority_document=self.session.authority_document,
                scan_result=self.session.scan_result,
                verify_report=self.session.verify_report,
            )
        return self.review_service.load()

    def run(self) -> DriftGateResult:
        """Run auto-sync and Drift Gate decisions.

        Returns:
            Drift gate result.
        """
        if self.cached_human_items:
            self.result.cache_hit = True
            human_items = self._filter_known_human_decisions(self.cached_human_items)
            return self._review_human_items(human_items=human_items, snapshot=None)

        cached_result = self._reuse_unchanged_drift_state()
        if cached_result is not None:
            return cached_result

        snapshot = self._load_review_snapshot()
        self.result.safe_mechanical_updates = self._apply_safe_mechanical_updates(snapshot)
        if self.result.safe_mechanical_updates:
            snapshot = self.review_service.load()

        human_items = self._filter_known_human_decisions(
            [item for item in snapshot.items if self._requires_human_decision(item)]
        )
        return self._review_human_items(human_items=human_items, snapshot=snapshot)

    def _review_human_items(
        self,
        human_items: list[DiffItem],
        snapshot: DiffReviewSnapshot | None,
    ) -> DriftGateResult:
        """Review human drift items, grouping package moves first.

        Args:
            human_items: Human-decision drift items.
            snapshot: Optional full review snapshot.

        Returns:
            Drift gate result.
        """
        if not human_items:
            self.drift_state.replace_pending_items([])
            self._save_drift_state(pending_human_decisions=0)
            return self.result

        self._active_human_items = list(human_items)
        self._active_index = 0
        self.drift_state.replace_pending_items(human_items)
        self._save_drift_state(pending_human_decisions=len(human_items))

        package_groups, ungrouped_items = group_package_moves(human_items)
        total_decisions = len(package_groups) + len(ungrouped_items)
        decision_index = 1
        for group in package_groups:
            self._active_index = decision_index
            should_continue = self._review_package_move(group=group, index=decision_index, total=total_decisions, snapshot=snapshot)
            remaining_items = _remaining_items_after_group(human_items, group, ungrouped_items, package_groups, decision_index)
            self.drift_state.replace_pending_items(remaining_items)
            self._save_drift_state(pending_human_decisions=len(remaining_items))
            if not should_continue:
                return self.result
            decision_index += 1
        for item in ungrouped_items:
            self._active_index = decision_index
            should_continue = self._review_item(item=item, index=decision_index, total=total_decisions, snapshot=snapshot)
            remaining_items = ungrouped_items[decision_index - len(package_groups):]
            self.drift_state.replace_pending_items(remaining_items)
            self._save_drift_state(pending_human_decisions=len(remaining_items))
            if not should_continue:
                return self.result
            decision_index += 1
        self.drift_state.replace_pending_items([])
        self._save_drift_state(pending_human_decisions=self.result.skipped_count)
        return self.result

    def _reuse_unchanged_drift_state(self) -> DriftGateResult | None:
        """Return cached Drift Gate result when project drift inputs are unchanged.

        Returns:
            Drift gate result when the previous state can be reused, otherwise None.
        """
        if not self.drift_state.is_reusable_for_signature(self.input_signature):
            return None
        self.result.cache_hit = True
        for issue in self.drift_state.restored_inspector_issues():
            self.result.approved_count += 1
            self.result.inspector_issues.append(issue)
        self.result.reused_decision_count = len(self.drift_state.decisions)
        return self.result

    def _filter_known_human_decisions(self, human_items: list[DiffItem]) -> list[DiffItem]:
        """Remove already-decided drift items from the current review list.

        Args:
            human_items: Human-decision drift items from the current snapshot.

        Returns:
            Items that still require Drift Gate review.
        """
        pending_items: list[DiffItem] = []
        for item in human_items:
            record = self.drift_state.current_record_for(item)
            if record is None:
                pending_items.append(item)
                continue
            if self._apply_cached_decision(record):
                continue
            pending_items.append(item)
        return pending_items

    def _apply_cached_decision(self, record: DriftDecisionRecord) -> bool:
        """Apply a previously recorded decision to the current run.

        Args:
            record: Persisted decision record.

        Returns:
            True when the current Drift Gate item should be skipped.
        """
        if record.status == "approved_for_inspector":
            issue = record.to_inspect_issue()
            if issue is None:
                return False
            self.result.approved_count += 1
            self.result.reused_decision_count += 1
            self.result.inspector_issues.append(issue)
            return True
        if record.status == "attached":
            self.result.attached_count += 1
            self.result.reused_decision_count += 1
            return True
        if record.status == "ignored":
            self.result.ignored_count += 1
            self.result.reused_decision_count += 1
            return True
        if record.status in {"rejected", "source_delete_marked"}:
            self.result.rejected_count += 1
            self.result.reused_decision_count += 1
            return True
        if record.status in {"resolved", "deferred"}:
            self.result.reused_decision_count += 1
            return True
        return False

    def _record_decision(
        self,
        item: DiffItem,
        status: str,
        decision: str,
        reason: str | None = None,
        issue: InspectIssue | None = None,
    ) -> None:
        """Record one Drift Gate decision in the persistent ledger.

        Args:
            item: Diff item being decided.
            status: Decision status.
            decision: Decision label.
            reason: Optional reason.
            issue: Optional inspector issue produced by this decision.
        """
        self.drift_state.record_decision(
            item=item,
            status=status,
            decision=decision,
            reason=reason,
            issue=issue,
        )
        self._save_current_progress()

    def _save_current_progress(self) -> None:
        """Persist already-taken decisions and remaining pending items.

        This method is intentionally called after every Drift Gate decision so
        that quitting with q, Ctrl+C, EOF, or a terminal close does not lose
        decisions already taken during the current session.
        """
        remaining_items = self._undecided_active_items()
        self.drift_state.replace_pending_items(remaining_items)
        self._save_drift_state(pending_human_decisions=len(remaining_items))

    def _undecided_active_items(self) -> list[DiffItem]:
        """Return active Drift Gate items without a current decision record.

        Returns:
            Active pending items that still require human review.
        """
        return [
            item
            for item in self._active_human_items
            if self.drift_state.current_record_for(item) is None
        ]

    def _save_drift_state(self, pending_human_decisions: int) -> None:
        """Persist current drift state for later inspector runs.

        Args:
            pending_human_decisions: Remaining human drift decisions.
        """
        from datetime import datetime, timezone

        self.drift_state.input_signature = self.input_signature
        self.drift_state.pending_human_decisions = max(pending_human_decisions, 0)
        self.drift_state.last_analyzed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        self.state_repository.save(self.drift_state)

    def _requires_human_decision(self, item: DiffItem) -> bool:
        """Return whether a diff item should be shown in Drift Gate.

        Args:
            item: Diff item from review service.

        Returns:
            True when the item is structural drift, not metadata-only work.
        """
        return item.kind not in {DiffItemKind.INCOMPLETE_METADATA, DiffItemKind.METADATA_DRIFT}

    def _apply_safe_mechanical_updates(self, snapshot: DiffReviewSnapshot) -> int:
        """Apply exact safe mechanical updates before human decisions.

        Args:
            snapshot: Current diff review snapshot.

        Returns:
            Number of applied mechanical updates.
        """
        requests: list[BlueprintChangeRequest] = []
        unit_by_key = _unit_by_key(snapshot)
        for item in snapshot.items:
            if item.kind != DiffItemKind.MOVED_CODE_CANDIDATE:
                continue
            request = self._safe_mechanical_request(item=item, unit_by_key=unit_by_key)
            if request is not None:
                requests.append(request)
        if not requests:
            return 0
        if not self._ensure_authority_write_ready("safe mechanical updates"):
            return 0
        progress_reporter = self._build_patch_progress_reporter(
            title="Applying safe mechanical updates",
            total=len(requests),
        )
        progress_reporter(0, len(requests), "starting")
        result = self.blueprint_engine.apply_changes(
            requests,
            write_context=PatchWriteContext(tool_name="inspector", allow_guarded_writes=False),
            progress_callback=progress_reporter,
        )
        if not result.success:
            for message in result.messages:
                self.print_func(message)
            if result.blocked_reason:
                self.print_func(result.blocked_reason)
            return 0
        return len(requests)

    def _safe_mechanical_request(
        self,
        item: DiffItem,
        unit_by_key: dict[tuple[str, str, str], DiscoveredCodeUnit],
    ) -> BlueprintChangeRequest | None:
        """Build a safe mechanical request when exact evidence exists.

        Args:
            item: Moved-code diff item.
            unit_by_key: Discovered code units keyed by code target.

        Returns:
            Safe mechanical request or None.
        """
        target = item.blueprint_target
        candidate = item.code_target or (item.candidates[0] if item.candidates else None)
        if target is None or target.source_shard_path is None or candidate is None:
            return None
        if len(item.candidates) != 1:
            return None
        unit = unit_by_key.get((candidate.path, candidate.symbol, candidate.kind))
        if unit is None:
            return None
        detected = target.block_data.get("detected")
        if not isinstance(detected, dict):
            return None
        old_hash = clean_string(detected.get("normalized_body_hash"))
        if old_hash is None or old_hash != unit.normalized_body_hash:
            return None
        dangerous_capabilities = unit.dangerous_capabilities or {}
        dangerous_added = any(bool(value) for value in dangerous_capabilities.values())
        evidence = MechanicalChangeEvidence(
            exact_content_match=True,
            one_to_one_match=True,
            symbol_kind_matches=(target.kind == candidate.kind),
            purpose_preserved=True,
            dangerous_capability_added=dangerous_added,
            competing_candidates=0,
            description="normalized_body_hash matched exactly",
        )
        if not evidence.is_safe_mechanical_match():
            return None
        return BlueprintChangeRequest(
            kind=BlueprintChangeKind.UPDATE_CODE_REFERENCE,
            source=BlueprintChangeSource.SAFE_MECHANICAL_UPDATE,
            mechanical_evidence=evidence,
            payload={
                "block_id": target.block_id,
                "source_shard_path": target.source_shard_path,
                "new_path": candidate.path,
                "new_symbol": candidate.symbol,
                "new_kind": candidate.kind,
                "new_name": candidate.symbol,
            },
            reason="Inspector auto-sync: exact moved-code match.",
        )


    def save_current_pending_on_interrupt(self) -> None:
        """Persist current pending Drift Gate state after interruption."""
        if self._active_human_items:
            self._save_current_progress()

    def _review_package_move(
        self,
        group: PackageMoveGroup,
        index: int,
        total: int,
        snapshot: DiffReviewSnapshot | None,
    ) -> bool:
        """Review one grouped package move decision.

        Args:
            group: Package move group.
            index: One-based decision index.
            total: Total decision count.
            snapshot: Optional full review snapshot.

        Returns:
            True to continue, False to stop.
        """
        while True:
            self._render_package_move(group=group, index=index, total=total)
            command = normalize_command(self.input_func("Choice: "))
            if is_quit_command(command):
                return self._stop(total_unresolved=total - index + 1)
            if command == "s":
                self.result.skipped_count += group.affected_count
                self.print_func("Decision skipped: This package move remains unresolved.")
                return True
            if command == "1":
                self._accept_package_move(group=group)
                return True
            if command == "2":
                for item_index, item in enumerate(group.items, start=1):
                    if not self._review_item(
                        item=item,
                        index=item_index,
                        total=group.affected_count,
                        snapshot=snapshot,
                    ):
                        return False
                return True
            if command == "3":
                for item in group.items:
                    self._record_decision(
                        item=item,
                        status="deferred",
                        decision="KEEP_BLUEPRINT_AS_TRUTH",
                        reason="Package move rejected; code must be restored later.",
                    )
                self.print_func("Decision recorded: Blueprint remains source of truth for this package move.")
                return True
            self.print_func("Unknown command.")

    def _render_buffered(self, render_body: Callable[[], None]) -> None:
        """Render one Drift Gate screen through a single terminal write.

        Args:
            render_body: Screen renderer that writes lines through ``print_func``.
        """
        if self._render_buffer_active:
            render_body()
            return

        original_print_func = self.print_func
        rendered_lines: list[str] = []

        def collect_line(line: str) -> None:
            """Collect one rendered line for the buffered terminal write.

            Args:
                line: Rendered line.
            """
            rendered_lines.append(str(line))

        self._render_buffer_active = True
        self.print_func = collect_line
        try:
            render_body()
        finally:
            self.print_func = original_print_func
            self._render_buffer_active = False

        if rendered_lines:
            original_print_func("\n".join(rendered_lines))

    def _print_cache_notice(self) -> None:
        """Print a compact cache notice when Drift Gate uses cached state."""
        if self.result.cache_hit:
            self.print_func("Cache: loaded pending drift snapshot; full scan/verify was skipped.")

    def _render_screen_header(self, index: int, total: int, risk: str, subtitle: str | None = None) -> None:
        """Render the common Drift Gate header.

        Args:
            index: One-based decision index.
            total: Total decisions in the current review scope.
            risk: Risk label shown on the right side of the header.
            subtitle: Optional line shown below the source line.
        """
        left_text = f"Decision {index} of {total}"
        right_text = f"Risk: {risk}"
        spacing = max(DRIFT_GATE_WIDTH - len(left_text) - len(right_text), 1)
        source = "cached pending drift snapshot" if self.result.cache_hit else "current drift analysis"

        self.print_func("")
        self.print_func("BPFW DRIFT GATE")
        self.print_func("=" * DRIFT_GATE_WIDTH)
        self.print_func(f"{left_text}{' ' * spacing}{right_text}")
        self.print_func(f"Source: {source}")
        if self.result.cache_hit:
            self._print_cache_notice()
        if subtitle:
            self.print_func(subtitle)
        self.print_func("")

    def _render_operation_box(self, title: str, lines: list[str]) -> None:
        """Render the focused operation box used by Drift Gate screens.

        Args:
            title: Main operation title.
            lines: Operation details displayed inside the box.
        """
        prefix = "+-- OPERATION UNDER REVIEW "
        top_line = f"{prefix}{'-' * (DRIFT_GATE_WIDTH - len(prefix) - 1)}+"
        self.print_func(top_line)
        self._render_box_line(title)
        for line in lines:
            self._render_box_line(line)
        self.print_func(f"+{'-' * (DRIFT_GATE_WIDTH - 2)}+")
        self.print_func("")

    def _render_box_line(self, text: str) -> None:
        """Render one box line and wrap it when needed.

        Args:
            text: Text to render inside the operation box.
        """
        if text == "":
            self.print_func(f"| {' ' * BOX_INNER_WIDTH} |")
            return
        lines = _wrap_operation_box_text(text)
        for line in lines:
            self.print_func(f"| {line.ljust(BOX_INNER_WIDTH)} |")

    def _render_progress_footer(self, index: int, total: int) -> None:
        """Render compact pending counters after a Drift Gate decision prompt.

        Args:
            index: One-based decision index.
            total: Total decisions in the current review scope.
        """
        self.print_func("Progress after this:")
        self.print_func(f"  decisions left:       {max(total - index, 0)}")
        self.print_func(f"  inspector candidates: {len(self.result.inspector_issues)}")

    def _render_package_move(self, group: PackageMoveGroup, index: int, total: int) -> None:
        """Render a grouped package move decision.

        Args:
            group: Package move group.
            index: One-based decision index.
            total: Total decision count.
        """
        if not self._render_buffer_active:
            self._render_buffered(lambda: self._render_package_move(group=group, index=index, total=total))
            return

        self._render_screen_header(index=index, total=total, risk="MEDIUM")
        self._render_operation_box(
            title="PACKAGE MOVE",
            lines=[
                "",
                f"  Before: {group.old_prefix}",
                f"  After:  {group.new_prefix}",
                "",
                f"  Affected declarations: {group.affected_count}",
            ],
        )
        self.print_func("BPFW found a package move.")
        self.print_func("")
        self.print_func("Choose how to handle this move:")
        self.print_func("")
        self.print_func("  [1] Accept this package move")
        self.print_func(f"      Update all {group.affected_count} declarations automatically.")
        self.print_func("")
        self.print_func("  [2] Review each declaration")
        self.print_func("      Safer, but slower.")
        self.print_func("")
        self.print_func("  [3] Reject this move")
        self.print_func("      Keep blueprint as source of truth. Code must be restored later.")
        self.print_func("")
        self.print_func("  [s] Skip for now")
        self.print_func("  [q] Quit")
        self.print_func("")
        self.print_func("Evidence:")
        self.print_func(f"  same relative path: {group.affected_count}")
        self.print_func(f"  same symbol:        {group.affected_count}")
        self.print_func(f"  same kind:          {group.affected_count}")
        self.print_func("  fingerprint:        partial or unavailable")

    def _accept_package_move(self, group: PackageMoveGroup) -> None:
        """Accept one package move and update all covered declarations.

        Args:
            group: Package move group to apply.
        """
        requests: list[BlueprintChangeRequest] = []
        for item in group.items:
            target = item.blueprint_target
            candidate = item.code_target or (item.candidates[0] if item.candidates else None)
            if target is None or target.source_shard_path is None or candidate is None:
                continue
            requests.append(
                BlueprintChangeRequest(
                    kind=BlueprintChangeKind.UPDATE_CODE_REFERENCE,
                    source=BlueprintChangeSource.INSPECTOR,
                    human_confirmed=True,
                    payload={
                        "block_id": target.block_id,
                        "source_shard_path": target.source_shard_path,
                        "new_path": candidate.path,
                        "new_symbol": candidate.symbol,
                        "new_kind": candidate.kind,
                        "new_name": candidate.symbol,
                    },
                    reason="Drift Gate decision: accept grouped package move.",
                )
            )
        if not requests:
            self.print_func("Cannot apply package move because no valid update requests were built.")
            return
        if not self._ensure_authority_write_ready("package move"):
            return
        progress_reporter = self._build_patch_progress_reporter(
            title="Applying package move",
            total=len(requests),
        )
        progress_reporter(0, len(requests), "starting")
        result = self.blueprint_engine.apply_changes(
            requests,
            write_context=PatchWriteContext(tool_name="inspector", allow_guarded_writes=False),
            progress_callback=progress_reporter,
        )
        if not result.success:
            if result.blocked_reason:
                self.print_func(result.blocked_reason)
            for message in result.messages:
                self.print_func(message)
            return
        self.result.changed_authority_count += len(requests)
        for item in group.items:
            self._record_decision(
                item=item,
                status="resolved",
                decision="ACCEPT_PACKAGE_MOVE",
                reason=f"{group.old_prefix}->{group.new_prefix}",
            )
        self.print_func("Decision recorded: Package move accepted.")
        self.print_func(f"Updated declarations: {len(requests)}")
        self.print_func(f"Pattern: {group.old_prefix} -> {group.new_prefix}")


    def _ensure_authority_write_ready(self, operation_label: str) -> bool:
        """Return whether Inspector can write authority immediately.

        Inspector must not silently trigger privileged unlock operations while a
        Drift Gate decision is being applied. If authority files are locked, the
        user receives an immediate instruction instead of a hidden sudo/password
        wait or a progress bar stuck at 0%.

        Args:
            operation_label: Human readable operation being attempted.

        Returns:
            True when authority appears writable, False when the operation should
            stop before applying any change.
        """
        status = get_authority_protection_status(project_root=self.project_root).status
        if status in {"locked", "degraded"}:
            self.print_func("")
            self.print_func(f"Cannot apply {operation_label}: authority is locked.")
            self.print_func("")
            self.print_func("No changes were applied.")
            self.print_func("")
            self.print_func("Run:")
            self.print_func("  bpfw unlock")
            self.print_func("")
            self.print_func("Then run:")
            self.print_func("  bpfw inspector")
            return False
        if status not in {"unlocked", "unsupported"}:
            self.print_func("")
            self.print_func(f"Cannot apply {operation_label}: authority write status is {status}.")
            self.print_func("No changes were applied.")
            self.print_func("Run bpfw status or bpfw unlock before retrying.")
            return False
        return True


    def _build_patch_progress_reporter(
        self,
        title: str,
        total: int,
    ) -> Callable[[int, int, str], None]:
        """Build a terminal progress reporter for long patch operations.

        Args:
            title: Human readable operation title.
            total: Total expected operation count.

        Returns:
            Callback compatible with the patch engine progress API.
        """
        last_percent = -1

        def report(completed: int, callback_total: int, step_label: str) -> None:
            """Print progress updates without flooding the terminal.

            Args:
                completed: Completed operation count.
                callback_total: Total operation count reported by the patch engine.
                step_label: Current operation label.
            """
            nonlocal last_percent
            effective_total = max(callback_total, total, 1)
            safe_completed = min(max(completed, 0), effective_total)
            percent = int((safe_completed / effective_total) * 100)
            should_print = (
                percent == 0
                or percent == 100
                or percent // 10 > last_percent // 10
                or safe_completed == effective_total
            )
            if not should_print:
                return
            last_percent = percent
            filled_width = int((percent / 100) * 20)
            bar = "#" * filled_width + "." * (20 - filled_width)
            self.print_func(
                f"{title}: [{bar}] {percent:3d}% "
                f"({safe_completed}/{effective_total}) {step_label}"
            )

        return report

    def _review_item(
        self,
        item: DiffItem,
        index: int,
        total: int,
        snapshot: DiffReviewSnapshot | None,
    ) -> bool:
        """Review one Drift Gate item.

        Args:
            item: Diff item to review.
            index: One-based item number.
            total: Total human decisions.
            snapshot: Current review snapshot.

        Returns:
            True to continue, False to stop.
        """
        if item.kind == DiffItemKind.UNDECLARED_CODE:
            return self._review_undeclared_code(item=item, index=index, total=total, snapshot=snapshot)
        if item.kind in {DiffItemKind.MISSING_DECLARED_CODE, DiffItemKind.MOVED_CODE_CANDIDATE}:
            return self._review_missing_or_moved(item=item, index=index, total=total, snapshot=snapshot)
        if item.kind == DiffItemKind.DUPLICATE_ACTIVE_PURPOSE:
            return self._review_duplicate_active_purpose(item=item, index=index, total=total)
        return self._review_generic(item=item, index=index, total=total)

    def _review_undeclared_code(
        self,
        item: DiffItem,
        index: int,
        total: int,
        snapshot: DiffReviewSnapshot | None,
    ) -> bool:
        """Review an undeclared code target.

        Args:
            item: Undeclared-code item.
            index: One-based item number.
            total: Total human decisions.
            snapshot: Current review snapshot.

        Returns:
            True to continue, False to stop.
        """
        while True:
            self._render_undeclared_code(item=item, index=index, total=total)
            command = normalize_command(self.input_func("Choice: "))
            if is_quit_command(command):
                return self._stop(total_unresolved=total - index + 1)
            if command == "s":
                self.result.skipped_count += 1
                self.print_func("Decision skipped: This drift remains unresolved.")
                return True
            if command in {"1", "2"}:
                status = "active" if command == "1" else "experimental"
                issue = self._issue_from_code_target(
                    item=item,
                    snapshot=snapshot,
                    status=status,
                    issue_type="approved_new",
                    context_line=(
                        "Current item: approved new active responsibility from Drift Gate."
                        if status == "active"
                        else "Current item: approved experimental responsibility from Drift Gate."
                    ),
                )
                if issue is None:
                    self.print_func("Cannot approve this item because the code target is unavailable.")
                    return True
                self.result.approved_count += 1
                self.result.inspector_issues.append(issue)
                self._record_decision(
                    item=item,
                    status="approved_for_inspector",
                    decision=f"APPROVED_{status.upper()}",
                    issue=issue,
                )
                if status == "active":
                    self.print_func("Decision recorded: Approved as new active responsibility.")
                else:
                    self.print_func("Decision recorded: Approved as experimental responsibility.")
                self.print_func("This block will be opened in Inspector for metadata completion.")
                return True
            if command == "3":
                self._attach_to_existing(item=item, snapshot=snapshot)
                return True
            if command == "4":
                self._ignore_undeclared_code(item=item)
                return True
            if command == "5":
                self._reject_undeclared_code(item=item)
                return True
            self.print_func("Unknown command.")

    def _render_undeclared_code(self, item: DiffItem, index: int, total: int) -> None:
        """Render undeclared-code Drift Gate screen.

        Args:
            item: Undeclared-code item.
            index: One-based item number.
            total: Total human decisions.
        """
        if not self._render_buffer_active:
            self._render_buffered(lambda: self._render_undeclared_code(item=item, index=index, total=total))
            return

        code = item.code_target
        operation_lines = [""]
        if code is not None:
            operation_lines.append(f"  New code: {code.display_label()}")
            operation_lines.append("")
            operation_lines.append(f"  Kind: {code.kind}")
            if code.start_line is not None and code.end_line is not None:
                operation_lines.append(f"  Lines: {code.start_line}-{code.end_line}")
        else:
            operation_lines.append("  New code: unavailable")

        self._render_screen_header(index=index, total=total, risk=item.risk.value)
        self._render_operation_box(title="NEW UNDECLARED CODE", lines=operation_lines)
        self.print_func("BPFW found code that is not declared in blueprint.")
        self.print_func("")
        self.print_func("What is this code?")
        self.print_func("")
        self.print_func("  [1] A real active responsibility")
        self.print_func("      Add it to Inspector for metadata completion.")
        self.print_func("")
        self.print_func("  [2] Experimental code")
        self.print_func("      Add it, but not as the main active path.")
        self.print_func("")
        self.print_func("  [3] Part of an existing responsibility")
        self.print_func("      Attach it to another declared block.")
        self.print_func("")
        self.print_func("  [4] Internal/helper code")
        self.print_func("      Ignore it.")
        self.print_func("")
        self.print_func("  [5] Code that should not exist")
        self.print_func("      Reject it.")
        self.print_func("")
        self.print_func("  [s] Skip for now")
        self.print_func("  [q] Quit")
        self.print_func("")
        self._render_progress_footer(index=index, total=total)
        self.print_func("")
        self.print_func("Evidence:")
        if code is not None:
            self.print_func(f"  Kind: {code.kind}")
            if code.start_line is not None and code.end_line is not None:
                self.print_func(f"  Lines: {code.start_line}-{code.end_line}")
        self.print_func(f"  Risk: {item.risk.value}")
        self.print_func("  Fingerprint: available")
        self.print_func("  Source: scanner")

    def _review_missing_or_moved(
        self,
        item: DiffItem,
        index: int,
        total: int,
        snapshot: DiffReviewSnapshot | None,
    ) -> bool:
        """Review a missing declaration or moved-code candidate.

        Args:
            item: Missing or moved-code item.
            index: One-based item number.
            total: Total human decisions.
            snapshot: Current review snapshot.

        Returns:
            True to continue, False to stop.
        """
        while True:
            self._render_missing_or_moved(item=item, index=index, total=total)
            command = normalize_command(self.input_func("Choice: "))
            if is_quit_command(command):
                return self._stop(total_unresolved=total - index + 1)
            if command == "s":
                self.result.skipped_count += 1
                self.print_func("Decision skipped: This drift remains unresolved.")
                return True
            if command == "1":
                self._record_decision(
                    item=item,
                    status="deferred",
                    decision="KEEP_BLUEPRINT_AS_TRUTH",
                    reason="Code must be restored later.",
                )
                self.print_func("Decision recorded: Blueprint remains source of truth.")
                self.print_func("Meaning: Code must be restored later.")
                return True
            if command == "2":
                self._accept_candidate_as_same_responsibility(item=item)
                return True
            if command == "3":
                issue = self._issue_from_candidate(
                    item=item,
                    snapshot=snapshot,
                    status="experimental",
                    issue_type="drift_candidate",
                    context_line="Current item: candidate approved as experimental responsibility from Drift Gate.",
                )
                if issue is not None:
                    self.result.approved_count += 1
                    self.result.inspector_issues.append(issue)
                    self._record_decision(
                        item=item,
                        status="approved_for_inspector",
                        decision="APPROVED_CANDIDATE_EXPERIMENTAL",
                        issue=issue,
                    )
                    self.print_func("Decision recorded: Candidate approved as experimental responsibility.")
                return True
            if command == "4":
                self._mark_existing_block(item=item, status="deprecated")
                return True
            if command == "5":
                self._mark_existing_block(item=item, status="legacy")
                return True
            if command == "6":
                self._remove_existing_block(item=item)
                return True
            self.print_func("Unknown command.")

    def _render_missing_or_moved(self, item: DiffItem, index: int, total: int) -> None:
        """Render missing/moved Drift Gate screen.

        Args:
            item: Missing or moved-code item.
            index: One-based item number.
            total: Total human decisions.
        """
        if not self._render_buffer_active:
            self._render_buffered(lambda: self._render_missing_or_moved(item=item, index=index, total=total))
            return

        target = item.blueprint_target
        candidate = item.code_target or (item.candidates[0] if item.candidates else None)
        if candidate is None:
            operation_title = "MISSING DECLARED CODE"
            operation_lines = [
                "",
                f"  Blueprint: {_target_location(target)}",
                "  Codebase:  NOT FOUND",
                "",
                f"  Declaration ID: {_target_block_id(target)}",
            ]
        else:
            operation_title = "POSSIBLE MOVED OR RENAMED CODE"
            operation_lines = [
                "",
                f"  Before: {_target_location(target)}",
                f"  After:  {candidate.display_label()}",
                "",
                "  Match confidence: weak",
            ]

        self._render_screen_header(index=index, total=total, risk=item.risk.value)
        self._render_operation_box(title=operation_title, lines=operation_lines)
        if candidate is None:
            self.print_func("Blueprint declares code that no longer exists in the project.")
            self.print_func("")
            self.print_func("What happened?")
            self.print_func("")
            self.print_func("  [1] The code was removed by mistake")
            self.print_func("      Keep blueprint as truth. Restore the code later.")
        else:
            self.print_func("Blueprint target was not found, but BPFW found a possible match.")
            self.print_func("")
            self.print_func("What happened?")
            self.print_func("")
            self.print_func("  [1] The candidate is wrong")
            self.print_func("      Keep blueprint as truth. Restore the old target later.")
            self.print_func("")
            self.print_func("  [2] This is the same responsibility")
            self.print_func("      Update blueprint to the new location.")
            self.print_func("")
            self.print_func("  [3] This is different experimental code")
            self.print_func("      Add candidate as experimental responsibility.")
        self.print_func("")
        self.print_func("  [4] Old declaration is deprecated")
        self.print_func("      Keep the old declaration, but mark it deprecated.")
        self.print_func("")
        self.print_func("  [5] Old declaration is legacy")
        self.print_func("      Keep the old declaration as legacy authority.")
        self.print_func("")
        self.print_func("  [6] Old declaration should be removed")
        self.print_func("      Delete the old declaration from blueprint.")
        self.print_func("")
        self.print_func("  [s] Skip for now")
        self.print_func("  [q] Quit")
        self.print_func("")
        self._render_progress_footer(index=index, total=total)
        self.print_func("")
        self.print_func("Evidence:")
        if target is not None:
            self.print_func(f"  declared kind: {target.kind or '-'}")
        self.print_func("  Current code: missing" if candidate is None else "  Candidate evidence: weak match")
        self.print_func(f"  risk: {item.risk.value}")

    def _review_duplicate_active_purpose(self, item: DiffItem, index: int, total: int) -> bool:
        """Review duplicate active purpose drift.

        Args:
            item: Duplicate active purpose item.
            index: One-based item number.
            total: Total human decisions.

        Returns:
            True to continue, False to stop.
        """
        while True:
            self._render_duplicate_active_purpose(item=item, index=index, total=total)
            command = normalize_command(self.input_func("Choice: "))
            if is_quit_command(command):
                return self._stop(total_unresolved=total - index + 1)
            if command == "s":
                self.result.skipped_count += 1
                self.print_func("Decision skipped: This duplicate remains unresolved.")
                return True
            blocks = list(item.related_blocks)
            if command in {"1", "2", "3", "4"} and len(blocks) >= 2:
                keep_index = 0 if command in {"1", "3"} else 1
                change_index = 1 if keep_index == 0 else 0
                status = "experimental" if command in {"1", "2"} else "deprecated"
                if self._mark_target_status(blocks[change_index], status=status):
                    self._record_decision(
                        item=item,
                        status="resolved",
                        decision=f"RESOLVE_DUPLICATE_MARK_{status.upper()}",
                        reason=f"keep={blocks[keep_index].block_id}; change={blocks[change_index].block_id}",
                    )
                    self.print_func(
                        f"Decision recorded: {blocks[keep_index].block_id} remains active. "
                        f"{blocks[change_index].block_id} marked {status}."
                    )
                return True
            if command == "5":
                self._mark_duplicate_intentional(item=item)
                return True
            if command in {"6", "7"} and len(blocks) >= 2:
                selected_index = 0 if command == "6" else 1
                issue = self._issue_from_blueprint_target(
                    target=blocks[selected_index],
                    issue_type="duplicate_code",
                    context_line="Current item: duplicate active purpose selected for metadata inspection.",
                )
                if issue is not None:
                    self.result.inspector_issues.append(issue)
                    self.result.approved_count += 1
                    self._record_decision(
                        item=item,
                        status="approved_for_inspector",
                        decision="SEND_DUPLICATE_TO_INSPECTOR",
                        issue=issue,
                    )
                return True
            self.print_func("Unknown command.")

    def _render_duplicate_active_purpose(self, item: DiffItem, index: int, total: int) -> None:
        """Render duplicate-active-purpose Drift Gate screen.

        Args:
            item: Duplicate active purpose item.
            index: One-based item number.
            total: Total human decisions.
        """
        if not self._render_buffer_active:
            self._render_buffered(lambda: self._render_duplicate_active_purpose(item=item, index=index, total=total))
            return

        purpose = item.finding.evidence.get("purpose") if item.finding is not None else None
        operation_lines = ["", f"  Purpose: {purpose or '-'}", ""]
        for label, block in zip(("A", "B"), item.related_blocks):
            operation_lines.append(f"  {label}: {block.display_label()}")
            operation_lines.append(f"     lifecycle: {block.status or '-'}")
            operation_lines.append("")

        self._render_screen_header(index=index, total=total, risk=item.risk.value)
        self._render_operation_box(title="DUPLICATE ACTIVE PURPOSE", lines=operation_lines)
        self.print_func("Two active blocks declare the same purpose.")
        self.print_func("")
        self.print_func("Only one should remain active unless this duplicate is intentional.")
        self.print_func("")
        self.print_func("What should BPFW do?")
        self.print_func("")
        self.print_func("  [1] Keep A active, mark B experimental")
        self.print_func("      A remains the main implementation. B is kept for review.")
        self.print_func("")
        self.print_func("  [2] Keep B active, mark A experimental")
        self.print_func("      B becomes the main implementation. A is kept for review.")
        self.print_func("")
        self.print_func("  [3] Keep A active, mark B deprecated")
        self.print_func("      A remains active. B is marked as no longer preferred.")
        self.print_func("")
        self.print_func("  [4] Keep B active, mark A deprecated")
        self.print_func("      B remains active. A is marked as no longer preferred.")
        self.print_func("")
        self.print_func("  [5] This duplicate is intentional")
        self.print_func("      Keep both, but require explicit authority metadata.")
        self.print_func("")
        self.print_func("  [6] Send A to Inspector")
        self.print_func("      Review A before deciding.")
        self.print_func("")
        self.print_func("  [7] Send B to Inspector")
        self.print_func("      Review B before deciding.")
        self.print_func("")
        self.print_func("  [s] Skip for now")
        self.print_func("  [q] Quit")
        self.print_func("")
        self.print_func("Rule:")
        self.print_func("  BPFW never allows duplicate active purposes silently.")

    def _review_generic(self, item: DiffItem, index: int, total: int) -> bool:
        """Review a generic structural drift item.

        Args:
            item: Diff item.
            index: One-based item number.
            total: Total human decisions.

        Returns:
            True to continue, False to stop.
        """
        self._render_generic(item=item, index=index, total=total)
        command = normalize_command(self.input_func("Choice: "))
        if is_quit_command(command):
            return self._stop(total_unresolved=total - index + 1)
        self.result.skipped_count += 1
        return True

    def _render_generic(self, item: DiffItem, index: int, total: int) -> None:
        """Render a generic structural drift screen.

        Args:
            item: Diff item.
            index: One-based item number.
            total: Total human decisions.
        """
        if not self._render_buffer_active:
            self._render_buffered(lambda: self._render_generic(item=item, index=index, total=total))
            return

        self._render_screen_header(index=index, total=total, risk=item.risk.value)
        self._render_operation_box(
            title="STRUCTURAL DRIFT",
            lines=[
                "",
                f"  Type: {item.kind.value}",
                "",
                f"  {item.reason}",
            ],
        )
        self.print_func("BPFW found structural drift that needs manual review.")
        self.print_func("")
        self.print_func("Available actions:")
        self.print_func("")
        self.print_func("  [s] Skip for now")
        self.print_func("  [q] Quit")
        self.print_func("")

    def _issue_from_code_target(
        self,
        item: DiffItem,
        snapshot: DiffReviewSnapshot | None,
        status: str,
        issue_type: str,
        context_line: str,
    ) -> InspectIssue | None:
        """Create an inspector issue from an undeclared code target.

        Args:
            item: Diff item containing code target.
            snapshot: Current review snapshot.
            status: Initial lifecycle/status for the new block.
            issue_type: Inspector issue type label.
            context_line: Context line to show in Inspector.

        Returns:
            Inspector issue or None.
        """
        code = item.code_target
        if code is None:
            return None
        unit = _unit_by_key(snapshot).get((code.path, code.symbol, code.kind)) if snapshot is not None else None
        if unit is not None:
            block = build_new_detected_responsibility(unit)
        else:
            block = _block_from_code_target(code)
        block["status"] = status
        issue = InspectIssue(issue_type=issue_type, block=block, add_on_accept=True)
        issue.context_lines.append(context_line)
        return issue

    def _issue_from_candidate(
        self,
        item: DiffItem,
        snapshot: DiffReviewSnapshot | None,
        status: str,
        issue_type: str,
        context_line: str,
    ) -> InspectIssue | None:
        """Create an inspector issue from the first moved-code candidate.

        Args:
            item: Diff item containing candidates.
            snapshot: Current review snapshot.
            status: Initial lifecycle/status for the candidate.
            issue_type: Inspector issue type label.
            context_line: Context line to show in Inspector.

        Returns:
            Inspector issue or None.
        """
        candidate = item.code_target or (item.candidates[0] if item.candidates else None)
        if candidate is None:
            return None
        proxy_item = DiffItem(
            identifier=item.identifier,
            kind=item.kind,
            action_level=item.action_level,
            risk=item.risk,
            reason=item.reason,
            finding=item.finding,
            code_target=candidate,
        )
        return self._issue_from_code_target(
            item=proxy_item,
            snapshot=snapshot,
            status=status,
            issue_type=issue_type,
            context_line=context_line,
        )

    def _issue_from_blueprint_target(
        self,
        target: BlueprintTarget,
        issue_type: str,
        context_line: str,
    ) -> InspectIssue | None:
        """Create an inspector issue from an existing blueprint target.

        Args:
            target: Existing authority block target.
            issue_type: Inspector issue type label.
            context_line: Context line to show in Inspector.

        Returns:
            Inspector issue or None.
        """
        if not target.block_data:
            return None
        issue = InspectIssue(issue_type=issue_type, block=target.block_data, add_on_accept=False)
        issue.context_lines.append(context_line)
        return issue

    def _attach_to_existing(self, item: DiffItem, snapshot: DiffReviewSnapshot) -> None:
        """Attach undeclared code as covered code under an existing responsibility.

        Args:
            item: Undeclared-code item.
            snapshot: Current review snapshot.
        """
        code = item.code_target
        if code is None:
            self.print_func("Cannot attach because the code target is unavailable.")
            return
        blocks = _existing_blocks(snapshot) if snapshot is not None else _existing_blocks_from_session(self.session)
        if not blocks:
            self.print_func("No existing responsibilities are available.")
            return
        self.print_func("")
        self.print_func("Attach to existing responsibility")
        self.print_func(f"Target: {code.display_label()}")
        self.print_func("Candidates:")
        for index, block in enumerate(blocks[:10], start=1):
            self.print_func(f"  [{index}] {block.block_id} {block.path}::{block.symbol} purpose: {block.purpose or '-'}")
        self.print_func("  [b] Back")
        command = normalize_command(self.input_func("Choice: "))
        if command == "b" or not command.isdigit():
            return
        selected_index = int(command) - 1
        if selected_index < 0 or selected_index >= min(len(blocks), 10):
            self.print_func("Invalid candidate.")
            return
        selected = blocks[selected_index]
        request = BlueprintChangeRequest(
            kind=BlueprintChangeKind.ADD_COVERED_CODE,
            source=BlueprintChangeSource.INSPECTOR,
            human_confirmed=True,
            payload={
                "rule_data": {
                    "path": code.path,
                    "symbol": code.symbol,
                    "kind": code.kind,
                    "covered_by": selected.block_id,
                    "reason": "covered implementation detail",
                }
            },
            reason="Drift Gate decision: attach code to existing responsibility.",
        )
        if self._apply_authority_change(request):
            self.result.attached_count += 1
            self._record_decision(
                item=item,
                status="attached",
                decision="ATTACH_TO_EXISTING",
                reason=f"covered_by={selected.block_id}",
            )
            self.print_func("Decision recorded: Attached code as covered implementation detail.")
            self.print_func(f"Covered code: {code.display_label()}")
            self.print_func(f"Covered by: {selected.block_id}")
            self.print_func("Inspector: Not required for this decision.")

    def _ignore_undeclared_code(self, item: DiffItem) -> None:
        """Add an ignored-code rule for an undeclared code target.

        Args:
            item: Undeclared-code item.
        """
        code = item.code_target
        if code is None:
            self.print_func("Cannot ignore because the code target is unavailable.")
            return
        self.print_func("")
        self.print_func("Ignore undeclared code")
        self.print_func(f"Target: {code.display_label()}")
        self.print_func("Reason:")
        self.print_func("  [1] internal helper")
        self.print_func("  [2] generated code")
        self.print_func("  [3] test/demo helper")
        self.print_func("  [4] temporary local experiment")
        self.print_func("  [5] custom reason")
        self.print_func("  [b] Back")
        command = normalize_command(self.input_func("Choice: "))
        reasons = {
            "1": "internal helper",
            "2": "generated code",
            "3": "test/demo helper",
            "4": "temporary local experiment",
        }
        if command == "b":
            return
        reason = reasons.get(command)
        if command == "5":
            reason = self.input_func("Custom reason: ").strip() or "custom reason"
        if reason is None:
            return
        request = BlueprintChangeRequest(
            kind=BlueprintChangeKind.ADD_IGNORE_RULE,
            source=BlueprintChangeSource.INSPECTOR,
            human_confirmed=True,
            payload={
                "rule_data": {
                    "path": code.path,
                    "symbol": code.symbol,
                    "kind": code.kind,
                    "reason": reason,
                }
            },
            reason="Drift Gate decision: ignore undeclared code.",
        )
        if self._apply_authority_change(request):
            self.result.ignored_count += 1
            self._record_decision(
                item=item,
                status="ignored",
                decision="IGNORE_UNDECLARED_CODE",
                reason=reason,
            )
            self.print_func("Decision recorded: Ignore rule added.")
            self.print_func(f"Reason: {reason}")
            self.print_func("Inspector: Not required for this decision.")

    def _reject_undeclared_code(self, item: DiffItem) -> None:
        """Record a source deletion candidate without deleting source code.

        Args:
            item: Undeclared-code item.
        """
        code = item.code_target
        if code is None:
            self.print_func("Cannot reject because the code target is unavailable.")
            return
        self.print_func("")
        self.print_func("Reject code")
        self.print_func(f"Target: {code.display_label()}")
        self.print_func("BPFW will not delete source code automatically in this MVP.")
        self.print_func("Confirm:")
        self.print_func("  [1] Mark for source deletion")
        self.print_func("  [b] Back")
        command = normalize_command(self.input_func("Choice: "))
        if command != "1":
            return
        self.result.rejected_count += 1
        self._record_decision(
            item=item,
            status="source_delete_marked",
            decision="REJECT_CODE",
            reason="source deletion candidate",
        )
        self.print_func("Decision recorded: Source deletion candidate marked.")
        self.print_func(f"Source: {code.display_label()}")
        self.print_func("Inspector: Not required for this decision.")

    def _accept_candidate_as_same_responsibility(self, item: DiffItem) -> None:
        """Update an existing block to a candidate code target by human confirmation.

        Args:
            item: Missing or moved-code item.
        """
        target = item.blueprint_target
        candidate = item.code_target or (item.candidates[0] if item.candidates else None)
        if target is None or target.source_shard_path is None or candidate is None:
            self.print_func("Cannot update this declaration because target data is incomplete.")
            return
        request = BlueprintChangeRequest(
            kind=BlueprintChangeKind.UPDATE_CODE_REFERENCE,
            source=BlueprintChangeSource.INSPECTOR,
            human_confirmed=True,
            payload={
                "block_id": target.block_id,
                "source_shard_path": target.source_shard_path,
                "new_path": candidate.path,
                "new_symbol": candidate.symbol,
                "new_kind": candidate.kind,
                "new_name": candidate.symbol,
            },
            reason="Drift Gate decision: accept candidate as same responsibility.",
        )
        if self._apply_authority_change(request):
            self._record_decision(
                item=item,
                status="resolved",
                decision="ACCEPT_CANDIDATE_AS_SAME_RESPONSIBILITY",
                reason=f"new={candidate.display_label()}",
            )
            self.print_func("Decision recorded: Candidate accepted as same responsibility by human confirmation.")
            self.print_func(f"Authority update: {target.block_id}")
            self.print_func(f"old: {target.path}::{target.symbol}")
            self.print_func(f"new: {candidate.display_label()}")

    def _mark_existing_block(self, item: DiffItem, status: str) -> None:
        """Mark an existing target block with a lifecycle/status value.

        Args:
            item: Diff item containing a blueprint target.
            status: New status value.
        """
        target = item.blueprint_target
        if target is None:
            self.print_func("Cannot update status because target block is unavailable.")
            return
        if self._mark_target_status(target=target, status=status):
            self._record_decision(
                item=item,
                status="resolved",
                decision=f"MARK_{status.upper()}",
            )

    def _mark_target_status(self, target: BlueprintTarget, status: str) -> bool:
        """Apply a status update to an existing target block.

        Args:
            target: Existing authority target.
            status: New status value.
        """
        if target.source_shard_path is None:
            self.print_func("Cannot update status because source shard is unavailable.")
            return False
        request = BlueprintChangeRequest(
            kind=BlueprintChangeKind.UPDATE_METADATA,
            source=BlueprintChangeSource.INSPECTOR,
            human_confirmed=True,
            payload={
                "block_id": target.block_id,
                "source_shard_path": target.source_shard_path,
                "metadata_changes": {"status": status, "lifecycle": status},
            },
            reason=f"Drift Gate decision: mark block as {status}.",
        )
        if self._apply_authority_change(request):
            self.print_func(f"Decision recorded: block {target.block_id} marked as {status}.")
            return True
        return False

    def _remove_existing_block(self, item: DiffItem) -> None:
        """Remove an existing authority declaration after human confirmation.

        Args:
            item: Diff item containing a blueprint target.
        """
        target = item.blueprint_target
        if target is None or target.source_shard_path is None:
            self.print_func("Cannot remove declaration because target block is unavailable.")
            return
        self.print_func("")
        self.print_func("Remove declaration")
        self.print_func(f"Block: {target.block_id}")
        self.print_func("This removes the authority declaration from blueprint. It does not delete source code.")
        self.print_func("Confirm:")
        self.print_func("  [1] Remove declaration")
        self.print_func("  [b] Back")
        command = normalize_command(self.input_func("Choice: "))
        if command != "1":
            return
        request = BlueprintChangeRequest(
            kind=BlueprintChangeKind.DELETE_BLOCK,
            source=BlueprintChangeSource.INSPECTOR,
            human_confirmed=True,
            payload={
                "block_id": target.block_id,
                "source_shard_path": target.source_shard_path,
            },
            reason="Drift Gate decision: remove old declaration.",
        )
        if self._apply_authority_change(request):
            self._record_decision(
                item=item,
                status="resolved",
                decision="REMOVE_DECLARATION",
            )
            self.print_func("Decision recorded: Declaration removed from blueprint.")
            self.print_func("Inspector: Not required for this decision.")

    def _mark_duplicate_intentional(self, item: DiffItem) -> None:
        """Mark a duplicate purpose as intentional in memory for current pass.

        Args:
            item: Duplicate active purpose item.
        """
        purpose = item.finding.evidence.get("purpose") if item.finding is not None else "duplicate"
        group_id = to_snake_case(str(purpose or "intentional_duplicate"))
        self.print_func("")
        self.print_func("Mark duplicate as intentional")
        self.print_func(f"Purpose: {purpose or '-'}")
        self.print_func(f"Duplicate group id: {group_id}")
        self.print_func("Reason:")
        self.print_func("  [1] format-specific implementations")
        self.print_func("  [2] platform-specific implementations")
        self.print_func("  [3] migration compatibility")
        self.print_func("  [4] custom reason")
        self.print_func("  [b] Back")
        command = normalize_command(self.input_func("Choice: "))
        reasons = {
            "1": "format-specific implementations",
            "2": "platform-specific implementations",
            "3": "migration compatibility",
        }
        if command == "b":
            return
        reason = reasons.get(command)
        if command == "4":
            reason = self.input_func("Custom reason: ").strip() or "custom reason"
        if reason is None:
            return
        self._record_decision(
            item=item,
            status="resolved",
            decision="MARK_DUPLICATE_INTENTIONAL",
            reason=reason,
        )
        self.print_func("Decision recorded: Duplicate marked intentional.")
        self.print_func(f"Group: {group_id}")
        self.print_func(f"Reason: {reason}")
        self.print_func("Inspector: Not required unless either block has incomplete metadata.")

    def _apply_authority_change(self, request: BlueprintChangeRequest) -> bool:
        """Apply an authority change through Blueprint Engine.

        Args:
            request: Human-confirmed authority change request.

        Returns:
            True when the change was applied.
        """
        if not self._ensure_authority_write_ready("authority change"):
            return False
        result = self.blueprint_engine.apply_change(
            request,
            write_context=PatchWriteContext(tool_name="inspector", allow_guarded_writes=False),
        )
        if result.success:
            self.result.changed_authority_count += 1
            return True
        if result.blocked_reason:
            self.print_func(result.blocked_reason)
        for message in result.messages:
            self.print_func(message)
        return False

    def _stop(self, total_unresolved: int) -> bool:
        """Stop Drift Gate without opening metadata inspection.

        Args:
            total_unresolved: Number of unresolved decisions left.

        Returns:
            Always False.
        """
        self.result.stopped = True
        self._save_current_progress()
        unresolved_count = len(self._undecided_active_items()) if self._active_human_items else total_unresolved
        self.print_func("")
        self.print_func("BPFW Inspector stopped.")
        self.print_func("No metadata inspection was opened.")
        self.print_func(f"Unresolved: Human drift decisions: {unresolved_count}")
        self.print_func("Next: Run bpfw inspector again to continue.")
        return False


def run_drift_gate(
    session: InspectLoadResult,
    input_func: InputFunc,
    print_func: PrintFunc,
    cached_human_items: list[DiffItem] | None = None,
    drift_state: DriftState | None = None,
    input_signature: str | None = None,
) -> DriftGateResult:
    """Run Drift Gate for an inspector session.

    Args:
        session: Loaded inspector session.
        input_func: Function used to read user input.
        print_func: Function used to print terminal output.
        cached_human_items: Optional cached pending human decisions.
        drift_state: Optional preloaded drift state.
        input_signature: Optional precomputed input signature.

    Returns:
        Drift Gate result.
    """
    runner = DriftGateRunner(
        session=session,
        input_func=input_func,
        print_func=print_func,
        cached_human_items=cached_human_items,
        drift_state=drift_state,
        input_signature=input_signature,
    )
    try:
        return runner.run()
    except KeyboardInterrupt:
        runner.save_current_pending_on_interrupt()
        raise


def merge_drift_gate_into_session(session: InspectLoadResult, result: DriftGateResult) -> None:
    """Merge Drift Gate output into a loaded inspector session.

    Args:
        session: Inspector session to update.
        result: Drift Gate result.
    """
    base_context = result.build_context_lines()
    if result.stopped:
        return
    if not _has_meaningful_context(result):
        return
    existing_issues = [issue for issue in session.issues if issue.issue_type != ISSUE_NEW_DETECTED]
    for issue in result.inspector_issues:
        issue.context_lines = [*base_context, *issue.context_lines]
    for issue in existing_issues:
        if not issue.context_lines:
            issue.context_lines = list(base_context)
    session.issues = [*result.inspector_issues, *existing_issues]
    session.pre_inspection_context_lines = base_context


def rebuild_metadata_issues_after_authority_changes(session: InspectLoadResult) -> None:
    """Remove stale new-detected issues and keep metadata-only issues.

    Args:
        session: Inspector session to normalize.
    """
    session.incomplete = get_incomplete_blocks(session.blueprint_data)
    session.issues = [InspectIssue(issue_type="draft", block=block) for block in session.incomplete]


def _has_meaningful_context(result: DriftGateResult) -> bool:
    """Return whether Drift Gate result should be shown in Inspector context.

    Args:
        result: Drift Gate result.

    Returns:
        True when there is a prior action worth explaining.
    """
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


def _unit_by_key(snapshot: DiffReviewSnapshot) -> dict[tuple[str, str, str], DiscoveredCodeUnit]:
    """Return discovered code units keyed by path, symbol, and kind.

    Args:
        snapshot: Diff review snapshot.

    Returns:
        Mapping from code target key to discovered unit.
    """
    if snapshot.scan_result is None:
        return {}
    return {
        (unit.path, unit.symbol, unit.symbol_type): unit
        for unit in snapshot.scan_result.discovered_units
    }


def _existing_blocks(snapshot: DiffReviewSnapshot) -> list[BlueprintTarget]:
    """Return existing authority blocks from a review snapshot.

    Args:
        snapshot: Diff review snapshot.

    Returns:
        Blueprint targets for existing blocks.
    """
    blocks = snapshot.blueprint_data.get("blocks", [])
    if not isinstance(blocks, list):
        return []
    targets: list[BlueprintTarget] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        code = block.get("code") if isinstance(block.get("code"), dict) else {}
        block_id = clean_string(block.get("id"))
        if block_id is None:
            continue
        origin = snapshot.authority_document.get_origin(block_id) if snapshot.authority_document is not None else None
        targets.append(
            BlueprintTarget(
                block_id=block_id,
                path=clean_string(code.get("path")),
                symbol=clean_string(code.get("symbol")),
                kind=clean_string(code.get("kind")),
                source_shard_path=origin,
                purpose=clean_string(block.get("purpose")),
                name=clean_string(block.get("name")),
                domain=clean_string(block.get("domain")),
                status=clean_string(block.get("status")),
                block_data=block,
            )
        )
    return targets


def _block_from_code_target(code: CodeTarget) -> dict[str, Any]:
    """Build a minimal block when a discovered unit is unavailable.

    Args:
        code: Code target.

    Returns:
        Minimal authority block.
    """
    return {
        "id": to_snake_case(code.symbol),
        "purpose": None,
        "name": code.symbol,
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


def _existing_blocks_from_session(session: InspectLoadResult) -> list[BlueprintTarget]:
    """Return existing authority blocks from an inspector session.

    Args:
        session: Inspector session.

    Returns:
        Blueprint targets for existing blocks.
    """
    blocks = session.blueprint_data.get("blocks", [])
    if not isinstance(blocks, list):
        return []
    targets: list[BlueprintTarget] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        code = block.get("code") if isinstance(block.get("code"), dict) else {}
        block_id = clean_string(block.get("id"))
        if block_id is None:
            continue
        origin = session.authority_document.get_origin(block_id) if session.authority_document is not None else None
        targets.append(
            BlueprintTarget(
                block_id=block_id,
                path=clean_string(code.get("path")),
                symbol=clean_string(code.get("symbol")),
                kind=clean_string(code.get("kind")),
                source_shard_path=origin,
                purpose=clean_string(block.get("purpose")),
                name=clean_string(block.get("name")),
                domain=clean_string(block.get("domain")),
                status=clean_string(block.get("status")),
                block_data=block,
            )
        )
    return targets


def _target_location(target: BlueprintTarget | None) -> str:
    """Return a compact authority location for Drift Gate rendering.

    Args:
        target: Optional authority target.

    Returns:
        Human-readable code location.
    """
    if target is None:
        return "unavailable"
    if target.path and target.symbol:
        return f"{target.path}::{target.symbol}"
    return target.block_id


def _target_block_id(target: BlueprintTarget | None) -> str:
    """Return the authority block identifier for Drift Gate rendering.

    Args:
        target: Optional authority target.

    Returns:
        Authority block identifier or a placeholder.
    """
    if target is None:
        return "unavailable"
    return target.block_id


def _wrap_operation_box_text(text: str) -> list[str]:
    """Wrap one operation-box text line without changing semantic content.

    Args:
        text: Text to wrap.

    Returns:
        Wrapped lines sized for the operation box.
    """
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


def _remaining_items_after_group(
    original_items: list[DiffItem],
    group: PackageMoveGroup,
    ungrouped_items: list[DiffItem],
    package_groups: list[PackageMoveGroup],
    current_decision_index: int,
) -> list[DiffItem]:
    """Return remaining items after a package move decision.

    Args:
        original_items: Original human item list.
        group: Current group.
        ungrouped_items: Ungrouped items.
        package_groups: All package groups.
        current_decision_index: Current one-based package group index.

    Returns:
        Remaining pending diff items.
    """
    if current_decision_index <= 0:
        return list(original_items)
    remaining_groups = package_groups[current_decision_index:]
    remaining: list[DiffItem] = []
    for remaining_group in remaining_groups:
        remaining.extend(remaining_group.items)
    remaining.extend(ungrouped_items)
    return remaining
