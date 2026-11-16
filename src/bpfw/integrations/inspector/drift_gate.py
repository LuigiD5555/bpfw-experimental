"""Drift Gate workflow used before inspector metadata editing."""

from collections.abc import Callable
import copy
from pathlib import Path
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
    sort_inspect_issues_hierarchically,
)
from bpfw.integrations.inspector.drift_state import (
    DriftDecisionRecord,
    DriftState,
    DriftStateRepository,
)
from bpfw.integrations.inspector.drift_gate_authority import DriftAuthorityActions, DriftAuthorityWriter
from bpfw.integrations.inspector.drift_gate_commands import (
    DriftDecisionEngine,
    DriftDecisionIntent,
)
from bpfw.integrations.inspector.drift_gate_models import DriftGateResult
from bpfw.integrations.inspector.drift_gate_render import DriftGateRenderer
from bpfw.integrations.inspector.drift_gate_targets import DriftIssueFactory, DriftTargetResolver
from bpfw.integrations.inspector.drift_gate_session import DriftDecisionSession
from bpfw.integrations.inspector.drift_gate_undo import DriftAuthorityUndo, DriftUndoSnapshot
from bpfw.integrations.inspector.drift_gate_review import (
    DriftReviewEntry,
    build_review_entries,
    remaining_items_after_entry,
)
from bpfw.integrations.inspector.drift_gate_policy import (
    DriftDecisionPolicy,
    MissingOrMovedCapabilities,
    UndeclaredCapabilities,
)
from bpfw.integrations.inspector.drift_gate_helpers import (
    BOX_INNER_WIDTH,
    DRIFT_GATE_WIDTH,
    block_from_code_target as _block_from_code_target,
    diff_item_touches_paths as _diff_item_touches_paths,
    has_meaningful_context as _has_meaningful_context,
    inspect_issue_code_key as _inspect_issue_code_key,
    target_block_id as _target_block_id,
    target_location as _target_location,
    wrap_operation_box_text as _wrap_operation_box_text,
)
from bpfw.integrations.shared.cli_runtime import normalize_command
from bpfw.shared.text import to_snake_case

InputFunc = Callable[[str], str]
PrintFunc = Callable[[str], None]


class _DriftBackRequested(Exception):
    """Signal that the user wants to return to the previous Drift Gate decision."""


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
        self.project_root = session.project_root
        self.input_func = input_func
        self.print_func = print_func
        self.review_service = DiffReviewService(session.project_root)
        self.blueprint_engine = BlueprintEngine(session.project_root)
        self.authority_writer = DriftAuthorityWriter(session.project_root)
        self.state_repository = DriftStateRepository(session.project_root)
        self.drift_state = drift_state if drift_state is not None else self.state_repository.load()
        self.input_signature = input_signature or self.state_repository.build_input_signature()
        self.cached_human_items = list(cached_human_items or [])
        self._active_human_items: list[DiffItem] = []
        self._active_index: int = 0
        self.target_resolver = DriftTargetResolver(self.project_root, session.authority_document)
        self.issue_factory = DriftIssueFactory()
        self._decision_undo_stack: list[DriftUndoSnapshot] = []
        self._current_undo_snapshot: DriftUndoSnapshot | None = None
        self.result = DriftGateResult()
        self.renderer = DriftGateRenderer(self.print_func, self.result, self._can_go_back)
        self.decision_session = DriftDecisionSession(
            repository=self.state_repository,
            state=self.drift_state,
            input_signature=self.input_signature,
        )
        self.authority_undo = DriftAuthorityUndo(self.project_root)

    @property
    def _authority_target_cache(self) -> dict[str, BlueprintTarget] | None:
        """Compatibility view of the extracted target resolver cache."""
        return self.target_resolver.cache

    @_authority_target_cache.setter
    def _authority_target_cache(self, value: dict[str, BlueprintTarget] | None) -> None:
        self.target_resolver.cache = value

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
        """Review human drift items with in-session transactional back support.

        Args:
            human_items: Human-decision drift items.
            snapshot: Optional full review snapshot.

        Returns:
            Drift gate result.
        """
        if not human_items:
            self.decision_session.finish(unresolved_count=0)
            return self.result

        self._active_human_items = list(human_items)
        self.decision_session.active_items = self._active_human_items
        self._active_index = 0
        self._decision_undo_stack.clear()
        self._current_undo_snapshot = None
        self.decision_session.begin(human_items)

        package_groups, ungrouped_items = group_package_moves(human_items)
        review_entries = build_review_entries(
            package_groups=package_groups,
            ungrouped_items=ungrouped_items,
        )
        total_decisions = len(review_entries)
        entry_index = 0
        while entry_index < total_decisions:
            entry = review_entries[entry_index]
            decision_index = entry_index + 1
            self._active_index = decision_index
            undo_snapshot = self._capture_undo_snapshot(entry_index=entry_index)
            self._current_undo_snapshot = undo_snapshot
            try:
                should_continue = self._review_entry(
                    entry=entry,
                    index=decision_index,
                    total=total_decisions,
                    snapshot=snapshot,
                )
            except _DriftBackRequested:
                self._current_undo_snapshot = None
                restored_index = self._restore_previous_decision()
                if restored_index is None:
                    continue
                entry_index = restored_index
                self._active_index = entry_index + 1
                continue
            finally:
                if self._current_undo_snapshot is undo_snapshot:
                    self._current_undo_snapshot = None

            if not should_continue:
                return self.result

            self._decision_undo_stack.append(undo_snapshot)
            self.result.reviewed_human_item_count += 1
            entry_index += 1
            remaining_items = remaining_items_after_entry(
                review_entries=review_entries,
                next_entry_index=entry_index,
            )
            self.decision_session.replace_pending(remaining_items)

        self.decision_session.finish(unresolved_count=self.result.skipped_count)
        self._decision_undo_stack.clear()
        self._current_undo_snapshot = None
        return self.result

    def _review_entry(
        self,
        entry: DriftReviewEntry,
        index: int,
        total: int,
        snapshot: DiffReviewSnapshot | None,
    ) -> bool:
        """Review one linear Drift Gate entry.

        Args:
            entry: Review entry.
            index: One-based decision index.
            total: Total review entries.
            snapshot: Optional full review snapshot.

        Returns:
            True to continue, False to stop.
        """
        if entry.kind == "package" and entry.group is not None:
            return self._review_package_move(group=entry.group, index=index, total=total, snapshot=snapshot)
        if entry.item is None:
            return True
        return self._review_item(item=entry.item, index=index, total=total, snapshot=snapshot)

    def _capture_undo_snapshot(self, entry_index: int) -> DriftUndoSnapshot:
        """Capture the reversible state before one Drift Gate decision.

        Args:
            entry_index: Review entry index being displayed.

        Returns:
            Undo snapshot for the current decision.
        """
        return DriftUndoSnapshot(
            entry_index=entry_index,
            drift_state_data=copy.deepcopy(self.drift_state.to_json()),
            result=copy.deepcopy(self.result),
            input_signature=self.input_signature,
        )

    def _can_go_back(self) -> bool:
        """Return whether a previous Drift Gate decision can be restored.

        Returns:
            True when the in-session undo stack has at least one decision.
        """
        return bool(self._decision_undo_stack)

    def _request_back(self) -> None:
        """Request restoring the previous Drift Gate decision."""
        raise _DriftBackRequested()

    def _restore_previous_decision(self) -> int | None:
        """Restore the previous Drift Gate decision snapshot.

        Returns:
            Entry index to display again, or None when there is no history.
        """
        if not self._decision_undo_stack:
            self.print_func("No previous Drift Gate decision to restore.")
            return None
        snapshot = self._decision_undo_stack[-1]
        if not self._restore_authority_files(snapshot):
            return None
        self._decision_undo_stack.pop()
        self.drift_state = DriftState.from_json(copy.deepcopy(snapshot.drift_state_data))
        self.result = copy.deepcopy(snapshot.result)
        self.input_signature = snapshot.input_signature
        self.decision_session.state = self.drift_state
        self.decision_session.input_signature = self.input_signature or ""
        self.decision_session.active_items = self._active_human_items
        self.target_resolver.cache = None
        self.state_repository.save(self.drift_state)
        self.print_func("Back: previous Drift Gate decision was restored.")
        return snapshot.entry_index

    def _ensure_current_undo_has_authority_files(self) -> None:
        """Attach authority file contents to the active undo snapshot once.

        Authority snapshots are captured lazily so metadata-only decisions do not
        copy YAML files unnecessarily.
        """
        snapshot = self._current_undo_snapshot
        if snapshot is None or snapshot.authority_files is not None:
            return
        snapshot.authority_files = self._read_authority_file_snapshot()

    def _read_authority_file_snapshot(self) -> dict[str, str]:
        """Capture current authority files for in-session undo."""
        return self.authority_undo.capture()

    def _restore_authority_files(self, snapshot: DriftUndoSnapshot) -> bool:
        """Transactionally restore authority files captured by an undo snapshot."""
        if snapshot.authority_files is None:
            return True
        outcome = self.authority_undo.restore(snapshot.authority_files)
        if outcome.success:
            return True
        self.print_func(f"Back failed: authority could not be restored: {outcome.error or 'unknown error'}")
        if outcome.recovery_preserved:
            self.print_func("Recovery data was preserved in .bpfw/blueprint_engine_backup.")
        return False

    def _reuse_unchanged_drift_state(self) -> DriftGateResult | None:
        """Return cached Drift Gate result when project drift inputs are unchanged.

        Returns:
            Drift gate result when the previous state can be reused, otherwise None.
        """
        if self.drift_state.changed_paths or self.drift_state.added_paths or self.drift_state.removed_paths:
            return None
        if not self.drift_state.is_reusable_for_signature(self.input_signature):
            return None
        self.result.cache_hit = True
        for issue in self.drift_state.restored_inspector_issues():
            self.result.approved_count += 1
            self.result.inspector_issues.append(issue)
        self.result.reused_decision_count = len(self.drift_state.decisions)
        return self.result

    def _filter_known_human_decisions(self, human_items: list[DiffItem]) -> list[DiffItem]:
        """Remove already-decided drift items from the current review list."""
        pending_items: list[DiffItem] = []
        self.decision_session.state = self.drift_state
        for item in human_items:
            record = self.decision_session.current_reusable_record(item)
            if record is None:
                pending_items.append(item)
                continue
            if self._apply_cached_decision(record):
                continue
            pending_items.append(item)
        return pending_items

    def _apply_cached_decision(self, record: DriftDecisionRecord) -> bool:
        """Apply a previously recorded decision to the current run."""
        effect = self.decision_session.cached_effect(record)
        if not effect.reusable:
            return False
        self.result.approved_count += effect.approved
        self.result.attached_count += effect.attached
        self.result.ignored_count += effect.ignored
        self.result.rejected_count += effect.rejected
        self.result.reused_decision_count += effect.reused
        if effect.issue is not None:
            self.result.inspector_issues.append(effect.issue)
        return True

    def _record_decision(
        self,
        item: DiffItem,
        status: str,
        decision: str,
        reason: str | None = None,
        issue: InspectIssue | None = None,
    ) -> None:
        """Record one Drift Gate decision through the non-interactive session."""
        self.decision_session.record_decision(
            item=item,
            status=status,
            decision=decision,
            reason=reason,
            issue=issue,
        )

    def _save_current_progress(self) -> None:
        """Persist decisions and unresolved active items through the decision session."""
        self.decision_session.active_items = self._active_human_items
        self.decision_session.save_current_progress()

    def _undecided_active_items(self) -> list[DiffItem]:
        """Return active Drift Gate items without a current decision record."""
        self.decision_session.active_items = self._active_human_items
        return self.decision_session.pending_items()

    def _save_drift_state(self, pending_human_decisions: int) -> None:
        """Persist current drift state through the decision session."""
        self.decision_session.state = self.drift_state
        self.decision_session.input_signature = self.input_signature
        self.decision_session.save(pending_human_decisions=pending_human_decisions)

    def _requires_human_decision(self, item: DiffItem) -> bool:
        """Return whether a diff item should be shown in Drift Gate.

        Args:
            item: Diff item from review service.

        Returns:
            True when the item is structural drift, not metadata-only work.
        """
        return DriftDecisionPolicy.requires_human_decision(item.kind)

    def _apply_safe_mechanical_updates(self, snapshot: DiffReviewSnapshot) -> int:
        """Apply exact safe safe file updates before human decisions."""
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
        self._ensure_current_undo_has_authority_files()
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
        """Build a safe file-change request when exact evidence exists."""
        target = self._hydrated_blueprint_target(item.blueprint_target)
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
        """Review one grouped package move through the pure decision engine."""
        while True:
            self._render_package_move(group=group, index=index, total=total)
            command = normalize_command(self.input_func("Choice: "))
            parsed = DriftDecisionEngine.package(command, can_go_back=self._can_go_back())
            intent = parsed.intent
            if intent == DriftDecisionIntent.QUIT:
                return self._stop(total_unresolved=total - index + 1)
            if intent == DriftDecisionIntent.BACK:
                self._request_back()
            if intent == DriftDecisionIntent.BACK_UNAVAILABLE:
                self.print_func("No previous Drift Gate decision to restore.")
                continue
            if intent == DriftDecisionIntent.SKIP:
                self.result.skipped_count += len(group.items)
                self.print_func("Decision skipped: This package move remains unresolved.")
                return True
            if intent == DriftDecisionIntent.PACKAGE_ACCEPT_MOVE:
                if self._accept_package_move(group=group):
                    return True
                self.print_func("Option [1] was not completed. Choose another available option or retry.")
                continue
            if intent == DriftDecisionIntent.PACKAGE_REVIEW_INDIVIDUAL:
                for item_index, item in enumerate(group.items, start=1):
                    if not self._review_item(
                        item=item,
                        index=item_index,
                        total=len(group.items),
                        snapshot=snapshot,
                    ):
                        return False
                return True
            if intent == DriftDecisionIntent.PACKAGE_KEEP_BLUEPRINT:
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








    def _render_package_move(self, group: PackageMoveGroup, index: int, total: int) -> None:
        """Compatibility wrapper around the isolated Drift Gate renderer."""
        self.renderer.package_move(group=group, index=index, total=total)

    def _render_undeclared_code(
        self,
        item: DiffItem,
        index: int,
        total: int,
        snapshot: DiffReviewSnapshot | None = None,
    ) -> None:
        """Render undeclared code with precomputed command capabilities."""
        self.renderer.undeclared_code(
            item=item,
            index=index,
            total=total,
            available_commands=self._available_undeclared_commands(item=item, snapshot=snapshot),
        )

    def _render_missing_or_moved(self, item: DiffItem, index: int, total: int) -> None:
        """Render missing/moved code with precomputed command capabilities."""
        self.renderer.missing_or_moved(
            item=item,
            index=index,
            total=total,
            available_commands=self._available_missing_or_moved_commands(item),
        )

    def _render_duplicate_active_purpose(self, item: DiffItem, index: int, total: int) -> None:
        """Render duplicate-purpose decisions through the isolated renderer."""
        self.renderer.duplicate_active_purpose(item=item, index=index, total=total)

    def _render_generic(self, item: DiffItem, index: int, total: int) -> None:
        """Render generic structural drift through the isolated renderer."""
        self.renderer.generic(item=item, index=index, total=total)

    def _accept_package_move(self, group: PackageMoveGroup) -> bool:
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
            return False
        if not self._ensure_authority_write_ready("package move"):
            return False
        progress_reporter = self._build_patch_progress_reporter(
            title="Applying package move",
            total=len(requests),
        )
        progress_reporter(0, len(requests), "starting")
        self._ensure_current_undo_has_authority_files()
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
            return False
        self.result.changed_authority_count += len(requests)
        self._refresh_input_signature_after_authority_change()
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
        return True


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

    def _refresh_input_signature_after_authority_change(self) -> None:
        """Refresh the drift cache signature after authority files are changed."""
        try:
            self.input_signature = self.state_repository.build_input_signature()
            self.decision_session.input_signature = self.input_signature
        except OSError:
            return


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
        """Review undeclared code while delegating command semantics to DecisionEngine."""
        while True:
            self._render_undeclared_code(item=item, index=index, total=total, snapshot=snapshot)
            command = normalize_command(self.input_func("Choice: "))
            available_commands = self._available_undeclared_commands(item=item, snapshot=snapshot)
            parsed = DriftDecisionEngine.undeclared(
                command,
                available_commands=available_commands,
                can_go_back=self._can_go_back(),
            )
            intent = parsed.intent
            if intent == DriftDecisionIntent.QUIT:
                return self._stop(total_unresolved=total - index + 1)
            if intent == DriftDecisionIntent.BACK:
                self._request_back()
            if intent in {DriftDecisionIntent.BACK_UNAVAILABLE, DriftDecisionIntent.UNAVAILABLE, DriftDecisionIntent.UNKNOWN}:
                self._print_unavailable_command(command=command, available_commands=available_commands)
                continue
            if intent == DriftDecisionIntent.SKIP:
                self.result.skipped_count += 1
                self.print_func("Decision skipped: This drift remains unresolved.")
                return True
            if intent in {
                DriftDecisionIntent.UNDECLARED_APPROVE_ACTIVE,
                DriftDecisionIntent.UNDECLARED_APPROVE_EXPERIMENTAL,
            }:
                status = (
                    "active"
                    if intent == DriftDecisionIntent.UNDECLARED_APPROVE_ACTIVE
                    else "experimental"
                )
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
                    self.print_func(f"Option [{command}] was disabled after validation because the code target is unavailable.")
                    continue
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
            if intent == DriftDecisionIntent.UNDECLARED_ATTACH:
                if self._attach_to_existing(item=item, snapshot=snapshot):
                    return True
                self.print_func("Option [3] was not completed. Choose another available option or retry.")
                continue
            if intent == DriftDecisionIntent.UNDECLARED_IGNORE:
                if self._ignore_undeclared_code(item=item):
                    return True
                self.print_func("Option [4] was not completed. Choose another available option or retry.")
                continue
            if intent == DriftDecisionIntent.UNDECLARED_REJECT:
                if self._reject_undeclared_code(item=item):
                    return True
                self.print_func("Option [5] was not completed. Choose another available option or retry.")
                continue

    def _available_undeclared_commands(
        self,
        item: DiffItem,
        snapshot: DiffReviewSnapshot | None,
    ) -> set[str]:
        """Return commands that can be executed for one undeclared-code item.

        Args:
            item: Undeclared-code diff item.
            snapshot: Optional current review snapshot.

        Returns:
            Normalized commands available for this screen.
        """
        blocks = _existing_blocks(snapshot) if snapshot is not None else _existing_blocks_from_session(self.session)
        return DriftDecisionPolicy.undeclared_commands(
            UndeclaredCapabilities(
                code_target_available=item.code_target is not None,
                existing_responsibilities_available=bool(blocks),
                can_go_back=self._can_go_back(),
            )
        )


    def _review_missing_or_moved(
        self,
        item: DiffItem,
        index: int,
        total: int,
        snapshot: DiffReviewSnapshot | None,
    ) -> bool:
        """Review missing/moved code through explicit decision intents."""
        while True:
            self._render_missing_or_moved(item=item, index=index, total=total)
            command = normalize_command(self.input_func("Choice: "))
            available_commands = self._available_missing_or_moved_commands(item)
            parsed = DriftDecisionEngine.missing_or_moved(
                command,
                available_commands=available_commands,
                can_go_back=self._can_go_back(),
            )
            intent = parsed.intent
            if intent == DriftDecisionIntent.QUIT:
                return self._stop(total_unresolved=total - index + 1)
            if intent == DriftDecisionIntent.BACK:
                self._request_back()
            if intent in {DriftDecisionIntent.BACK_UNAVAILABLE, DriftDecisionIntent.UNAVAILABLE, DriftDecisionIntent.UNKNOWN}:
                self._print_unavailable_command(command=command, available_commands=available_commands)
                continue
            if intent == DriftDecisionIntent.SKIP:
                self.result.skipped_count += 1
                self.print_func("Decision skipped: This drift remains unresolved.")
                return True
            if intent == DriftDecisionIntent.MISSING_KEEP_BLUEPRINT:
                self._record_decision(
                    item=item,
                    status="deferred",
                    decision="KEEP_BLUEPRINT_AS_TRUTH",
                    reason="Code must be restored later.",
                )
                self.print_func("Decision recorded: Blueprint remains source of truth.")
                self.print_func("Meaning: Code must be restored later.")
                return True
            if intent == DriftDecisionIntent.MISSING_ACCEPT_CANDIDATE:
                if self._accept_candidate_as_same_responsibility(item=item):
                    return True
                self.print_func("Option [2] was disabled after validation because the authority update could not be applied.")
                continue
            if intent == DriftDecisionIntent.MISSING_APPROVE_EXPERIMENTAL:
                issue = self._issue_from_candidate(
                    item=item,
                    snapshot=snapshot,
                    status="experimental",
                    issue_type="drift_candidate",
                    context_line="Current item: candidate approved as experimental responsibility from Drift Gate.",
                )
                if issue is None:
                    self.print_func("Option [3] was disabled after validation because candidate data is incomplete.")
                    continue
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
            if intent == DriftDecisionIntent.MISSING_MARK_DEPRECATED:
                if self._mark_existing_block(item=item, status="deprecated"):
                    return True
                self.print_func("Option [4] was disabled after validation because the authority update could not be applied.")
                continue
            if intent == DriftDecisionIntent.MISSING_MARK_LEGACY:
                if self._mark_existing_block(item=item, status="legacy"):
                    return True
                self.print_func("Option [5] was disabled after validation because the authority update could not be applied.")
                continue
            if intent == DriftDecisionIntent.MISSING_REMOVE_DECLARATION:
                if self._remove_existing_block(item=item):
                    return True
                self.print_func("Option [6] was not completed. Choose another available option or retry.")
                continue






    def _hydrated_blueprint_target(self, target: BlueprintTarget | None) -> BlueprintTarget | None:
        """Hydrate a cached target from current authority when possible."""
        return self.target_resolver.hydrate(target)

    def _current_authority_target_by_id(self, block_id: str) -> BlueprintTarget | None:
        """Return a current authority target by stable block ID."""
        return self.target_resolver.by_id(block_id)

    def _find_authority_target_for_code(
        self, candidate: CodeTarget, exclude_block_id: str | None = None
    ) -> BlueprintTarget | None:
        """Find an existing authority declaration for one code target."""
        return self.target_resolver.find_for_code(candidate, exclude_block_id)

    def _issue_from_code_target(
        self, item: DiffItem, snapshot: DiffReviewSnapshot | None, status: str, issue_type: str, context_line: str
    ) -> InspectIssue | None:
        """Build an Inspector issue from an undeclared code target."""
        return self.issue_factory.from_code_target(item, snapshot, status, issue_type, context_line)

    def _issue_from_candidate(
        self, item: DiffItem, snapshot: DiffReviewSnapshot | None, status: str, issue_type: str, context_line: str
    ) -> InspectIssue | None:
        """Build an Inspector issue from a moved-code candidate."""
        return self.issue_factory.from_candidate(item, snapshot, status, issue_type, context_line)

    def _issue_from_blueprint_target(
        self, target: BlueprintTarget, issue_type: str, context_line: str
    ) -> InspectIssue | None:
        """Build an Inspector issue from current authority metadata."""
        return self.issue_factory.from_blueprint_target(target, issue_type, context_line)

    def _update_hydrated_target_cache(self, target: BlueprintTarget, candidate: CodeTarget) -> None:
        """Keep resolver cache coherent after an accepted code-reference update."""
        self.target_resolver.update_code_reference(target, candidate)

    def _remove_hydrated_target_from_cache(self, block_id: str) -> None:
        """Remove a deleted authority block from the resolver cache."""
        self.target_resolver.remove(block_id)

    def _available_missing_or_moved_commands(self, item: DiffItem) -> set[str]:
        """Return commands that can be executed for one missing/moved item.

        The rendered menu and command handler must use this same method so a
        displayed option is always executable and a hidden option cannot be
        triggered manually.

        Args:
            item: Missing or moved-code diff item.

        Returns:
            Normalized commands available for the current item.
        """
        target_writable = self._can_update_existing_block(item)
        return DriftDecisionPolicy.missing_or_moved_commands(
            MissingOrMovedCapabilities(
                candidate_available=self._can_approve_candidate_as_experimental(item),
                target_writable=target_writable,
                can_go_back=self._can_go_back(),
            )
        )

    def _can_accept_candidate_as_same_responsibility(self, item: DiffItem) -> bool:
        """Return whether option 2 can update the existing authority target.

        Args:
            item: Missing or moved-code diff item.

        Returns:
            True when the candidate and target contain the data required for an
            UPDATE_CODE_REFERENCE patch.
        """
        target = self._hydrated_blueprint_target(item.blueprint_target)
        candidate = item.code_target or (item.candidates[0] if item.candidates else None)
        return target is not None and target.source_shard_path is not None and candidate is not None

    def _can_approve_candidate_as_experimental(self, item: DiffItem) -> bool:
        """Return whether option 3 can create an inspector issue for a candidate.

        Args:
            item: Missing or moved-code diff item.

        Returns:
            True when a candidate code target exists.
        """
        candidate = item.code_target or (item.candidates[0] if item.candidates else None)
        return candidate is not None

    def _can_update_existing_block(self, item: DiffItem) -> bool:
        """Return whether lifecycle updates can be applied to the old block.

        Args:
            item: Missing or moved-code diff item.

        Returns:
            True when the old block and its source shard are known.
        """
        target = self._hydrated_blueprint_target(item.blueprint_target)
        return target is not None and target.source_shard_path is not None

    def _print_unavailable_command(self, command: str, available_commands: set[str]) -> None:
        """Print a consistent message for unavailable Drift Gate commands.

        Args:
            command: Normalized command entered by the user.
            available_commands: Commands allowed on the current screen.
        """
        if command == "":
            self.print_func("Unknown command.")
            return
        available_text = ", ".join(f"[{value}]" for value in sorted(available_commands) if value != "q")
        if command.isdigit():
            self.print_func(f"Option [{command}] is not available for this drift item.")
            self.print_func(f"Available options: {available_text}, [q].")
            return
        self.print_func("Unknown command.")


    def _review_duplicate_active_purpose(self, item: DiffItem, index: int, total: int) -> bool:
        """Review duplicate-active-purpose drift using explicit decision intents."""
        while True:
            self._render_duplicate_active_purpose(item=item, index=index, total=total)
            command = normalize_command(self.input_func("Choice: "))
            blocks = list(item.related_blocks)
            parsed = DriftDecisionEngine.duplicate(
                command,
                can_go_back=self._can_go_back(),
                block_count=len(blocks),
            )
            intent = parsed.intent
            if intent == DriftDecisionIntent.QUIT:
                return self._stop(total_unresolved=total - index + 1)
            if intent == DriftDecisionIntent.BACK:
                self._request_back()
            if intent == DriftDecisionIntent.BACK_UNAVAILABLE:
                self.print_func("No previous Drift Gate decision to restore.")
                continue
            if intent == DriftDecisionIntent.SKIP:
                self.result.skipped_count += 1
                self.print_func("Decision skipped: This duplicate remains unresolved.")
                return True

            lifecycle_actions = {
                DriftDecisionIntent.DUPLICATE_KEEP_A_MARK_B_EXPERIMENTAL: (0, 1, "experimental"),
                DriftDecisionIntent.DUPLICATE_KEEP_B_MARK_A_EXPERIMENTAL: (1, 0, "experimental"),
                DriftDecisionIntent.DUPLICATE_KEEP_A_MARK_B_DEPRECATED: (0, 1, "deprecated"),
                DriftDecisionIntent.DUPLICATE_KEEP_B_MARK_A_DEPRECATED: (1, 0, "deprecated"),
            }
            lifecycle_action = lifecycle_actions.get(intent)
            if lifecycle_action is not None:
                keep_index, change_index, status = lifecycle_action
                if not self._mark_target_status(blocks[change_index], status=status):
                    self.print_func("Lifecycle update was not completed. Choose another option or retry.")
                    continue
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
            if intent == DriftDecisionIntent.DUPLICATE_MARK_INTENTIONAL:
                if self._mark_duplicate_intentional(item=item):
                    return True
                continue
            if intent in {DriftDecisionIntent.DUPLICATE_INSPECT_A, DriftDecisionIntent.DUPLICATE_INSPECT_B}:
                selected_index = 0 if intent == DriftDecisionIntent.DUPLICATE_INSPECT_A else 1
                issue = self._issue_from_blueprint_target(
                    target=blocks[selected_index],
                    issue_type="duplicate_code",
                    context_line="Current item: duplicate active purpose selected for metadata inspection.",
                )
                if issue is None:
                    self.print_func("Inspector handoff was not completed because block data is unavailable.")
                    continue
                self.result.inspector_issues.append(issue)
                self.result.approved_count += 1
                self._record_decision(
                    item=item,
                    status="approved_for_inspector",
                    decision="SEND_DUPLICATE_TO_INSPECTOR",
                    issue=issue,
                )
                return True
            if intent == DriftDecisionIntent.UNAVAILABLE:
                self.print_func(f"Option [{command}] is not available for this duplicate.")
                continue
            self.print_func("Unknown command.")


    def _review_generic(self, item: DiffItem, index: int, total: int) -> bool:
        """Review generic structural drift through explicit decision intents."""
        while True:
            self._render_generic(item=item, index=index, total=total)
            command = normalize_command(self.input_func("Choice: "))
            parsed = DriftDecisionEngine.generic(command, can_go_back=self._can_go_back())
            intent = parsed.intent
            if intent == DriftDecisionIntent.QUIT:
                return self._stop(total_unresolved=total - index + 1)
            if intent == DriftDecisionIntent.BACK:
                self._request_back()
            if intent == DriftDecisionIntent.BACK_UNAVAILABLE:
                self.print_func("No previous Drift Gate decision to restore.")
                continue
            if intent == DriftDecisionIntent.SKIP:
                self.result.skipped_count += 1
                return True
            self.print_func("Unknown command.")





    def _attach_to_existing(self, item: DiffItem, snapshot: DiffReviewSnapshot | None) -> bool:
        """Attach undeclared code as covered code under an existing responsibility.

        Args:
            item: Undeclared-code item.
            snapshot: Current review snapshot.

        Returns:
            True when the attach decision was applied and recorded.
        """
        code = item.code_target
        if code is None:
            self.print_func("Cannot attach because the code target is unavailable.")
            return False
        blocks = _existing_blocks(snapshot) if snapshot is not None else _existing_blocks_from_session(self.session)
        if not blocks:
            self.print_func("No existing responsibilities are available.")
            return False
        self.print_func("")
        self.print_func("Attach to existing responsibility")
        self.print_func(f"Target: {code.display_label()}")
        self.print_func("Candidates:")
        for index, block in enumerate(blocks[:10], start=1):
            self.print_func(f"  [{index}] {block.block_id} {block.path}::{block.symbol} purpose: {block.purpose or '-'}")
        self.print_func("  [b] Back")
        command = normalize_command(self.input_func("Choice: "))
        if command == "b" or not command.isdigit():
            return False
        selected_index = int(command) - 1
        if selected_index < 0 or selected_index >= min(len(blocks), 10):
            self.print_func("Invalid candidate.")
            return False
        selected = blocks[selected_index]
        request = DriftAuthorityActions.attach_code_request(code=code, covered_by=selected.block_id)
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
            return True
        return False

    def _ignore_undeclared_code(self, item: DiffItem) -> bool:
        """Add an ignored-code rule for an undeclared code target.

        Args:
            item: Undeclared-code item.

        Returns:
            True when the ignore decision was applied and recorded.
        """
        code = item.code_target
        if code is None:
            self.print_func("Cannot ignore because the code target is unavailable.")
            return False
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
            return False
        reason = reasons.get(command)
        if command == "5":
            reason = self.input_func("Custom reason: ").strip() or "custom reason"
        if reason is None:
            return False
        request = DriftAuthorityActions.ignore_code_request(code=code, reason=reason)
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
            return True
        return False

    def _reject_undeclared_code(self, item: DiffItem) -> bool:
        """Record a source deletion candidate without deleting source code.

        Args:
            item: Undeclared-code item.

        Returns:
            True when the reject decision was recorded.
        """
        code = item.code_target
        if code is None:
            self.print_func("Cannot reject because the code target is unavailable.")
            return False
        self.print_func("")
        self.print_func("Reject code")
        self.print_func(f"Target: {code.display_label()}")
        self.print_func("BPFW will not delete source code automatically in this MVP.")
        self.print_func("Confirm:")
        self.print_func("  [1] Mark for source deletion")
        self.print_func("  [b] Back")
        command = normalize_command(self.input_func("Choice: "))
        if command != "1":
            return False
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
        return True

    def _accept_candidate_as_same_responsibility(self, item: DiffItem) -> bool:
        """Update or merge an existing block to a candidate code target.

        Args:
            item: Missing or moved-code item.

        Returns:
            True when the authority update was applied and the drift item was resolved.
        """
        target = self._hydrated_blueprint_target(item.blueprint_target)
        candidate = item.code_target or (item.candidates[0] if item.candidates else None)
        if target is None or target.source_shard_path is None or candidate is None:
            self.print_func("Cannot update this declaration because target data is incomplete.")
            return False

        existing_target = self._find_authority_target_for_code(
            candidate=candidate,
            exclude_block_id=target.block_id,
        )
        if existing_target is not None:
            return self._merge_same_responsibility_into_existing_declaration(
                item=item,
                old_target=target,
                existing_target=existing_target,
                candidate=candidate,
            )

        if self._apply_fast_code_reference_update(target=target, candidate=candidate):
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
            return True
        return False


    def _merge_same_responsibility_into_existing_declaration(
        self,
        item: DiffItem,
        old_target: BlueprintTarget,
        existing_target: BlueprintTarget,
        candidate: CodeTarget,
    ) -> bool:
        """Resolve a moved-code decision when the candidate is already declared.

        When the candidate already has an authority block, updating the old
        block to the same code target would create a duplicate declaration. In
        that case the human decision means the old declaration is stale and must
        be removed while the existing candidate declaration is kept.

        Args:
            item: Drift item being decided.
            old_target: Stale authority declaration.
            existing_target: Current declaration for the candidate code.
            candidate: Candidate code target selected by the user.

        Returns:
            True when the stale declaration was removed.
        """
        if old_target.source_shard_path is None:
            self.print_func("Cannot merge declarations because the stale block shard is unavailable.")
            return False
        if not self._apply_fast_block_delete(target=old_target):
            return False
        self._record_decision(
            item=item,
            status="resolved",
            decision="MERGE_WITH_EXISTING_DECLARATION",
            reason=f"existing={existing_target.block_id}; new={candidate.display_label()}",
        )
        self.print_func("Decision recorded: Candidate accepted as same responsibility by human confirmation.")
        self.print_func("Authority merge: candidate was already declared, so the stale old declaration was removed.")
        self.print_func(f"removed: {old_target.block_id}")
        self.print_func(f"kept:    {existing_target.block_id}")
        self.print_func(f"target:  {candidate.display_label()}")
        return True

    def _apply_fast_code_reference_update(self, target: BlueprintTarget, candidate: CodeTarget) -> bool:
        """Apply a single code-reference update without reparsing the full shard repeatedly.

        Drift Gate accepts many one-by-one moved-code decisions. Sending every
        small code-reference update through the full Blueprint Engine is safe,
        but it is unnecessarily expensive because it reloads, dumps, and
        validates the entire shard for each decision. This fast path performs a
        narrow text patch for the already-confirmed block ID while preserving the
        same authority-write gate.

        Args:
            target: Existing authority block to update.
            candidate: Confirmed code target selected by the user.

        Returns:
            True when the authority shard was updated.
        """
        if target.source_shard_path is None:
            self.print_func("Cannot update this declaration because source shard is unavailable.")
            return False
        if not self._ensure_authority_write_ready("authority change"):
            return False
        self._ensure_current_undo_has_authority_files()

        shard_path = target.source_shard_path
        shard_file = self.project_root / shard_path
        try:
            original_text = shard_file.read_text(encoding="utf-8")
        except OSError as error:
            self.print_func(f"Cannot read authority shard {shard_path}: {error}")
            return False

        updated_text = DriftAuthorityActions.replace_code_reference_in_shard_text(
            original_text=original_text,
            block_id=target.block_id,
            new_path=candidate.path,
            new_symbol=candidate.symbol,
            new_kind=candidate.kind,
            new_name=candidate.symbol,
        )
        if updated_text is None:
            self.print_func(f"Cannot update authority shard {shard_path}: block was not found.")
            return False
        if updated_text == original_text:
            self.print_func("Authority already points to the selected candidate.")
            return True

        write_result = self.authority_writer.write_text(shard_path, updated_text)
        if not write_result.success:
            self.print_func(f"Cannot update authority shard {shard_path}: {write_result.error or 'write failed'}")
            if write_result.recovery_preserved:
                self.print_func("Recovery data was preserved in .bpfw/blueprint_engine_backup.")
            return False

        self.result.changed_authority_count += 1
        self._update_hydrated_target_cache(target=target, candidate=candidate)
        self._refresh_input_signature_after_authority_change()
        return True

    def _apply_fast_block_delete(self, target: BlueprintTarget) -> bool:
        """Delete one stale authority block using a narrow text patch.

        Args:
            target: Authority block to delete.

        Returns:
            True when the block was removed from its shard.
        """
        if target.source_shard_path is None:
            self.print_func("Cannot remove declaration because source shard is unavailable.")
            return False
        if not self._ensure_authority_write_ready("authority change"):
            return False
        self._ensure_current_undo_has_authority_files()

        shard_path = target.source_shard_path
        shard_file = self.project_root / shard_path
        try:
            original_text = shard_file.read_text(encoding="utf-8")
        except OSError as error:
            self.print_func(f"Cannot read authority shard {shard_path}: {error}")
            return False

        updated_text = DriftAuthorityActions.remove_block_from_shard_text(
            original_text=original_text,
            block_id=target.block_id,
        )
        if updated_text is None:
            self.print_func(f"Cannot remove declaration from {shard_path}: block was not found.")
            return False

        write_result = self.authority_writer.write_text(shard_path, updated_text)
        if not write_result.success:
            self.print_func(f"Cannot remove declaration from {shard_path}: {write_result.error or 'write failed'}")
            if write_result.recovery_preserved:
                self.print_func("Recovery data was preserved in .bpfw/blueprint_engine_backup.")
            return False

        self.result.changed_authority_count += 1
        self._remove_hydrated_target_from_cache(target.block_id)
        self._refresh_input_signature_after_authority_change()
        return True



    def _mark_existing_block(self, item: DiffItem, status: str) -> bool:
        """Mark an existing target block with a lifecycle/status value.

        Args:
            item: Diff item containing a blueprint target.
            status: New status value.

        Returns:
            True when the status update was applied and the drift item was resolved.
        """
        target = self._hydrated_blueprint_target(item.blueprint_target)
        if target is None:
            self.print_func("Cannot update status because target block is unavailable.")
            return False
        if self._mark_target_status(target=target, status=status):
            self._record_decision(
                item=item,
                status="resolved",
                decision=f"MARK_{status.upper()}",
            )
            return True
        return False

    def _mark_target_status(self, target: BlueprintTarget, status: str) -> bool:
        """Apply a status update to an existing target block.

        Args:
            target: Existing authority target.
            status: New status value.
        """
        if target.source_shard_path is None:
            self.print_func("Cannot update status because source shard is unavailable.")
            return False
        request = DriftAuthorityActions.mark_status_request(target=target, status=status)
        if self._apply_authority_change(request):
            self.print_func(f"Decision recorded: block {target.block_id} marked as {status}.")
            return True
        return False

    def _remove_existing_block(self, item: DiffItem) -> bool:
        """Remove an existing authority declaration after human confirmation.

        Args:
            item: Diff item containing a blueprint target.

        Returns:
            True when the declaration was removed and the drift item was resolved.
        """
        target = self._hydrated_blueprint_target(item.blueprint_target)
        if target is None or target.source_shard_path is None:
            self.print_func("Cannot remove declaration because target block is unavailable.")
            return False
        self.print_func("")
        self.print_func("Remove declaration")
        self.print_func(f"Block: {target.block_id}")
        self.print_func("This removes the authority declaration from blueprint. It does not delete source code.")
        self.print_func("Confirm:")
        self.print_func("  [1] Remove declaration")
        self.print_func("  [b] Back")
        command = normalize_command(self.input_func("Choice: "))
        if command != "1":
            return False
        request = DriftAuthorityActions.delete_block_request(target)
        if self._apply_authority_change(request):
            self._record_decision(
                item=item,
                status="resolved",
                decision="REMOVE_DECLARATION",
            )
            self.print_func("Decision recorded: Declaration removed from blueprint.")
            self.print_func("Inspector: Not required for this decision.")
            return True
        return False

    def _mark_duplicate_intentional(self, item: DiffItem) -> bool:
        """Mark a duplicate purpose as intentional in memory for current pass.

        Args:
            item: Duplicate active purpose item.

        Returns:
            True only when a decision was actually recorded.
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
            return False
        reason = reasons.get(command)
        if command == "4":
            reason = self.input_func("Custom reason: ").strip() or "custom reason"
        if reason is None:
            return False
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
        return True

    def _apply_authority_change(self, request: BlueprintChangeRequest) -> bool:
        """Apply an authority change through Blueprint Engine.

        Args:
            request: Human-confirmed authority change request.

        Returns:
            True when the change was applied.
        """
        if not self._ensure_authority_write_ready("authority change"):
            return False
        self._ensure_current_undo_has_authority_files()
        result = self.blueprint_engine.apply_changes(
            [request],
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
    preserved_context = list(session.pre_inspection_context_lines)
    base_context = result.build_context_lines()
    if result.stopped:
        return
    if not _has_meaningful_context(result):
        return

    result_keys = {
        key
        for issue in result.inspector_issues
        for key in [_inspect_issue_code_key(issue)]
        if key is not None
    }
    existing_issues = [
        issue
        for issue in session.issues
        if issue.issue_type != ISSUE_NEW_DETECTED
        and _inspect_issue_code_key(issue) not in result_keys
    ]
    for issue in result.inspector_issues:
        issue.context_lines = [*base_context, *issue.context_lines]
    for issue in existing_issues:
        if not issue.context_lines:
            issue.context_lines = list(base_context)
    session.issues = sort_inspect_issues_hierarchically([*result.inspector_issues, *existing_issues])
    merged_context = [*preserved_context, *base_context]
    deduplicated_context = list(dict.fromkeys(merged_context))
    session.pre_inspection_context_lines = deduplicated_context




def rebuild_metadata_issues_after_authority_changes(session: InspectLoadResult) -> None:
    """Remove stale new-detected issues and keep metadata-only issues.

    Args:
        session: Inspector session to normalize.
    """
    session.incomplete = get_incomplete_blocks(session.blueprint_data)
    session.issues = sort_inspect_issues_hierarchically(
        [InspectIssue(issue_type="draft", block=block) for block in session.incomplete]
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
        origin = snapshot.authority_document.block_origins.get(block_id) if snapshot.authority_document is not None else None
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
        origin = session.authority_document.block_origins.get(block_id) if session.authority_document is not None else None
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


