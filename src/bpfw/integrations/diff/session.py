"""Interactive terminal session for ``bpfw diff``."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from bpfw.core.blueprint_engine import (
    BlueprintChangeKind,
    BlueprintChangeRequest,
    BlueprintChangeSource,
    BlueprintEngine as AuthorityBlueprintEngine,
)
from bpfw.core.authority.patch.transaction import PatchWriteContext
from bpfw.core.catalog.verify import run_verify
from bpfw.integrations.diff.metadata_window import MetadataDraft, run_metadata_window
from bpfw.integrations.diff.models import (
    BlueprintTarget,
    CodeTarget,
    DiffActionLevel,
    DiffItem,
    DiffItemKind,
    DiffRisk,
    SourceChangeKind,
    SourceChangeRequest,
)
from bpfw.integrations.diff.plan import (
    DiffApplyPlan,
    PlannedAuthorityAction,
    PlannedSourceAction,
    collect_file_stamps,
)
from bpfw.integrations.diff.review import DiffReviewService, DiffReviewSnapshot
from bpfw.integrations.inspector.base import apply_suggestions, build_new_detected_responsibility
from bpfw.integrations.shared.cli_runtime import is_back_command, is_quit_command, normalize_command
from bpfw.shared.text import to_snake_case

InputFunc = Callable[[str], str]
PrintFunc = Callable[[str], None]


class DiffSession:
    """Run the diff decision manager in an interactive terminal."""

    def __init__(
        self,
        project_root: Path,
        input_func: InputFunc = input,
        print_func: PrintFunc = print,
    ) -> None:
        """Initialize the diff session.

        Args:
            project_root: Project root directory.
            input_func: Function used to read terminal input.
            print_func: Function used to print terminal output.
        """
        self.project_root = project_root.resolve()
        self.input_func = input_func
        self.print_func = print_func
        self.review_service = DiffReviewService(self.project_root)
        self.blueprint_engine = AuthorityBlueprintEngine(self.project_root)
        self.plan = DiffApplyPlan()
        self.snapshot: DiffReviewSnapshot | None = None
        self.current_index = 0

    def run(self) -> int:
        """Run the interactive diff session.

        Returns:
            Process exit code.
        """
        self.snapshot = self.review_service.load()
        if not self.snapshot.items:
            self._render_no_findings()
            return 0

        try:
            while True:
                self._render_home()
                command = normalize_command(self.input_func("Choice: "))
                if is_quit_command(command):
                    return self._handle_quit()
                if command == "" or command == "r":
                    self._review_all()
                    continue
                if command == "g":
                    self._review_group()
                    continue
                if command == "p":
                    self._view_plan()
                    continue
                if command == "f":
                    self._render_filter_not_available()
                    continue
                if command == "h":
                    self._render_help()
                    continue
                if command.isdigit():
                    self._review_group_by_number(int(command))
                    continue
                self.print_func("Unknown command.")
        except EOFError:
            self.print_func("Interactive diff input unavailable.")
            return 1
        except KeyboardInterrupt:
            self.print_func("Diff stopped.")
            return 0

    def _render_home(self) -> None:
        """Render the diff manager home screen."""
        assert self.snapshot is not None
        counts = self._group_counts()
        self.print_func("")
        self.print_func("BPFW DIFF MANAGER")
        self.print_func("")
        self.print_func("Blueprint authority and real code are different.")
        self.print_func("")
        self.print_func("No files will be modified until you approve an apply plan.")
        self.print_func("")
        self.print_func("Groups:")
        ordered_groups = self._ordered_group_values()
        for index, group_name in enumerate(ordered_groups, start=1):
            self.print_func(f"  [{index}] {group_name:<28} {counts.get(group_name, 0)}")
        self.print_func("")
        self.print_func("Plan:")
        self.print_func(f"  Pending actions: {self.plan.action_count()}")
        self.print_func("")
        self.print_func("Options:")
        self.print_func("  [Enter] Review next")
        self.print_func("  [r] Review all")
        self.print_func("  [g] Review group")
        self.print_func("  [p] View apply plan")
        self.print_func("  [f] Filter")
        self.print_func("  [h] Help")
        self.print_func("  [q] Quit")
        self.print_func("")

    def _render_no_findings(self) -> None:
        """Render the no-findings screen."""
        self.print_func("")
        self.print_func("BPFW DIFF MANAGER")
        self.print_func("")
        self.print_func("No differences found.")
        self.print_func("")
        self.print_func("Blueprint authority matches current code scan.")
        self.print_func("")
        self.print_func("Next:")
        self.print_func("  bpfw verify")

    def _render_filter_not_available(self) -> None:
        """Show a small filter notice."""
        self.print_func("")
        self.print_func("FILTER DIFFS")
        self.print_func("")
        self.print_func("Filtering is reserved for the next UI pass.")
        self.print_func("Use [g] to review a group in this MVP version.")

    def _render_help(self) -> None:
        """Render diff manager help."""
        self.print_func("")
        self.print_func("BPFW DIFF HELP")
        self.print_func("")
        self.print_func("verify detects drift and never writes files.")
        self.print_func("diff owns the decision about each difference.")
        self.print_func("the inspector metadata window only edits metadata for a decision.")
        self.print_func("BlueprintEngine writes bpfw/* only after you apply the plan.")
        self.print_func("")
        self.print_func("Common flow:")
        self.print_func("  review diff item -> add decision to plan -> view plan -> apply plan")
        self.print_func("")

    def _review_all(self) -> None:
        """Review unresolved diff items in order."""
        assert self.snapshot is not None
        items = list(self.snapshot.items)
        for item in items[self.current_index:]:
            if item.identifier in self.plan.planned_item_ids():
                continue
            should_continue = self._review_item(item)
            if not should_continue:
                return
            self.current_index += 1

    def _review_group(self) -> None:
        """Prompt for a group and review that group."""
        self._render_group_selection()
        command = normalize_command(self.input_func("Choice: "))
        if command.isdigit():
            self._review_group_by_number(int(command))

    def _review_group_by_number(self, group_number: int) -> None:
        """Review one group by menu number.

        Args:
            group_number: One-based group index.
        """
        groups = self._ordered_group_values()
        selected_index = group_number - 1
        if selected_index < 0 or selected_index >= len(groups):
            self.print_func("Invalid group.")
            return
        group_name = groups[selected_index]
        assert self.snapshot is not None
        for item in self.snapshot.items:
            if item.action_level.value != group_name:
                continue
            if item.identifier in self.plan.planned_item_ids():
                continue
            should_continue = self._review_item(item)
            if not should_continue:
                return

    def _render_group_selection(self) -> None:
        """Render group selector."""
        counts = self._group_counts()
        self.print_func("")
        self.print_func("SELECT DIFF GROUP")
        self.print_func("")
        for index, group_name in enumerate(self._ordered_group_values(), start=1):
            self.print_func(f"  [{index}] {group_name:<28} {counts.get(group_name, 0)}")
        self.print_func("")
        self.print_func("Options:")
        self.print_func("  [b] Back")
        self.print_func("  [q] Quit")
        self.print_func("")

    def _review_item(self, item: DiffItem) -> bool:
        """Review one diff item.

        Args:
            item: Diff item to review.

        Returns:
            True to continue reviewing, False to return to the home screen.
        """
        if item.identifier in self.plan.planned_item_ids():
            return self._handle_already_planned(item)
        if item.kind == DiffItemKind.UNDECLARED_CODE:
            return self._review_undeclared_code(item)
        if item.kind == DiffItemKind.MISSING_DECLARED_CODE:
            return self._review_missing_declared_code(item)
        if item.kind == DiffItemKind.MOVED_CODE_CANDIDATE:
            return self._review_moved_code_candidate(item)
        if item.kind == DiffItemKind.DUPLICATE_ACTIVE_PURPOSE:
            return self._review_duplicate_active_purpose(item)
        if item.kind == DiffItemKind.INVALID_AUTHORITY:
            return self._review_invalid_authority(item)
        if item.kind == DiffItemKind.BROKEN_SHARD_REFERENCE:
            return self._review_broken_shard_reference(item)
        return self._review_generic_item(item)

    def _review_undeclared_code(self, item: DiffItem) -> bool:
        """Review an undeclared-code item.

        Args:
            item: Diff item.

        Returns:
            True to continue review, False to return home.
        """
        while True:
            self._render_undeclared_code(item)
            command = normalize_command(self.input_func("Choice: "))
            if is_quit_command(command):
                return False
            if is_back_command(command):
                return False
            if command in {"1", "2", "3"}:
                status = {"1": "active", "2": "experimental", "3": "legacy"}[command]
                self._quick_create_block(item, status)
                return True
            if command == "4":
                self._create_block_with_metadata_window(item)
                return True
            if command == "5":
                self._attach_to_existing_block(item)
                return True
            if command == "6":
                self._add_ignore_rule(item)
                return True
            if command == "7":
                self._add_source_delete_action(item)
                return True
            if command == "8":
                return True
            self.print_func("Unknown command.")

    def _render_undeclared_code(self, item: DiffItem) -> None:
        """Render the undeclared-code decision screen.

        Args:
            item: Diff item.
        """
        code = item.code_target
        self.print_func("")
        self.print_func(f"DIFF: {item.kind.value}")
        self.print_func("")
        self.print_func("BLUEPRINT")
        self.print_func("  No declaration found.")
        self.print_func("")
        self.print_func("CODE")
        if code is not None:
            self.print_func(f"  Path:   {code.path}")
            self.print_func(f"  Symbol: {code.symbol}")
            self.print_func(f"  Type:   {code.kind}")
            if code.start_line is not None and code.end_line is not None:
                self.print_func(f"  Lines:  {code.start_line}-{code.end_line}")
        else:
            self.print_func("  Could not resolve code target.")
        self.print_func("")
        self.print_func(f"Risk: {item.risk.value}")
        self.print_func(f"Reason: {item.reason}")
        self.print_func("")
        self.print_func("Options:")
        self.print_func("  [1] Add to blueprint as active")
        self.print_func("  [2] Add to blueprint as experimental")
        self.print_func("  [3] Add to blueprint as legacy")
        self.print_func("  [4] Open inspector metadata window")
        self.print_func("  [5] Attach to existing blueprint block")
        self.print_func("  [6] Ignore this code")
        self.print_func("  [7] Mark for source deletion")
        self.print_func("  [8] Skip")
        self.print_func("  [b] Back")
        self.print_func("  [q] Quit")
        self.print_func("")

    def _quick_create_block(self, item: DiffItem, status: str) -> None:
        """Create a block decision with detected metadata.

        Args:
            item: Diff item.
            status: Lifecycle/status selected by the user.
        """
        block = self._block_from_code_target(item, status=status)
        if block is None:
            self.print_func("Cannot create block because code target is unavailable.")
            return
        missing_purpose = not block.get("purpose")
        self.print_func("")
        self.print_func("DEFAULT METADATA PREVIEW")
        self.print_func("")
        self.print_func(f"  name:         {block.get('name')}")
        self.print_func(f"  purpose:      {block.get('purpose') or '<empty>'}")
        self.print_func(f"  domain:       {block.get('domain') or '<empty>'}")
        self.print_func(f"  lifecycle:    {block.get('status') or status}")
        if missing_purpose:
            self.print_func("")
            self.print_func("Warning:")
            self.print_func("  Purpose is empty.")
        self.print_func("")
        self.print_func("Options:")
        self.print_func("  [1] Add decision to plan anyway")
        self.print_func("  [2] Open inspector metadata window")
        self.print_func("  [3] Cancel")
        command = normalize_command(self.input_func("Choice: "))
        if command == "1":
            self._add_create_block_action(item=item, block=block)
        elif command == "2":
            self._create_block_with_metadata_window(item, block)

    def _create_block_with_metadata_window(self, item: DiffItem, block: dict[str, Any] | None = None) -> None:
        """Open metadata window before adding a create-block action.

        Args:
            item: Diff item.
            block: Optional prepared block.
        """
        prepared_block = block or self._block_from_code_target(item, status="experimental")
        if prepared_block is None:
            self.print_func("Cannot open metadata window because code target is unavailable.")
            return
        draft = run_metadata_window(
            block=prepared_block,
            title="INSPECT METADATA FOR DIFF",
            input_func=self.input_func,
            print_func=self.print_func,
        )
        if draft is None:
            return
        updated_block = draft.apply_to_block(prepared_block)
        self._render_save_metadata_summary(updated_block)
        command = normalize_command(self.input_func("Choice: "))
        if command in {"1", "2", "3"}:
            updated_block["status"] = {"1": "active", "2": "experimental", "3": "legacy"}[command]
            self._add_create_block_action(item=item, block=updated_block)

    def _render_save_metadata_summary(self, block: dict[str, Any]) -> None:
        """Render the save-metadata-to-decision summary.

        Args:
            block: Updated block data.
        """
        self.print_func("")
        self.print_func("SAVE METADATA TO DIFF DECISION")
        self.print_func("")
        self.print_func("This will not modify files yet.")
        self.print_func("")
        self.print_func("Prepared decision:")
        self.print_func("  Add undeclared code to blueprint.")
        self.print_func("")
        self.print_func("Metadata:")
        self.print_func(f"  name:      {block.get('name') or '<empty>'}")
        self.print_func(f"  purpose:   {block.get('purpose') or '<empty>'}")
        self.print_func(f"  domain:    {block.get('domain') or '<empty>'}")
        self.print_func(f"  lifecycle: {block.get('status') or '<empty>'}")
        self.print_func("")
        self.print_func("Options:")
        self.print_func("  [1] Add as active")
        self.print_func("  [2] Add as experimental")
        self.print_func("  [3] Add as legacy")
        self.print_func("  [b] Back")
        self.print_func("")

    def _add_create_block_action(self, item: DiffItem, block: dict[str, Any]) -> None:
        """Add a create-block authority action to the plan.

        Args:
            item: Diff item.
            block: Block data to create.
        """
        assert self.snapshot is not None
        target_shard = self.review_service.decide_shard_for_block(
            blueprint_data=self.snapshot.blueprint_data,
            authority_document=self.snapshot.authority_document,
            block_data=block,
        )
        request = BlueprintChangeRequest(
            kind=BlueprintChangeKind.CREATE_BLOCK,
            source=BlueprintChangeSource.DIFF,
            payload={
                "block_data": block,
                "target_shard_path": target_shard,
                "create_target_if_missing": True,
            },
            human_confirmed=True,
            reason="Diff decision: add undeclared code to blueprint.",
        )
        stamps = collect_file_stamps(self.project_root, [target_shard])
        conflicts = self.plan.add_authority_action(
            PlannedAuthorityAction(
                diff_item_id=item.identifier,
                label=f"CREATE_BLOCK {block.get('id')}",
                request=request,
                file_stamps=stamps,
            )
        )
        self._render_decision_added("CREATE_BLOCK", item, conflicts)

    def _attach_to_existing_block(self, item: DiffItem) -> None:
        """Add a covered-code decision for an undeclared code item.

        Args:
            item: Diff item.
        """
        code = item.code_target
        if code is None:
            self.print_func("Cannot attach because code target is unavailable.")
            return
        candidates = self._existing_block_candidates(code)
        if not candidates:
            self.print_func("No existing blueprint blocks are available.")
            return
        self.print_func("")
        self.print_func("ATTACH TO EXISTING BLUEPRINT BLOCK")
        self.print_func("")
        self.print_func(f"Code: {code.display_label()}")
        self.print_func("")
        self.print_func("Candidate blocks:")
        for index, block in enumerate(candidates, start=1):
            self.print_func(
                f"  [{index}] {block.get('id')} "
                f"domain={block.get('domain') or '<empty>'} "
                f"lifecycle={block.get('status') or block.get('lifecycle') or '<empty>'}"
            )
            purpose = str(block.get("purpose") or "").strip()
            if purpose:
                self.print_func(f"      purpose: {purpose}")
        self.print_func("")
        self.print_func("Options:")
        self.print_func("  [number] Attach to selected block")
        self.print_func("  [b] Back")
        command = normalize_command(self.input_func("Choice: "))
        if not command.isdigit():
            return
        selected_index = int(command) - 1
        if selected_index < 0 or selected_index >= len(candidates):
            self.print_func("Invalid block selection.")
            return
        selected_block = candidates[selected_index]
        block_id = str(selected_block.get("id") or "").strip()
        if not block_id:
            self.print_func("Selected block does not have an id.")
            return
        reason = self.input_func("Reason [belongs to existing authority block]: ").strip()
        if not reason:
            reason = "belongs to existing authority block"
        request = BlueprintChangeRequest(
            kind=BlueprintChangeKind.ADD_COVERED_CODE,
            source=BlueprintChangeSource.DIFF,
            payload={
                "rule_data": {
                    "path": code.path,
                    "symbol": code.symbol,
                    "kind": code.kind,
                    "covered_by": block_id,
                    "reason": reason,
                }
            },
            human_confirmed=True,
            reason="Diff decision: attach undeclared code to an existing blueprint block.",
        )
        stamps = collect_file_stamps(self.project_root, [Path("bpfw/blueprint.yaml")])
        conflicts = self.plan.add_authority_action(
            PlannedAuthorityAction(
                diff_item_id=item.identifier,
                label=f"ADD_COVERED_CODE {code.display_label()} -> {block_id}",
                request=request,
                file_stamps=stamps,
            )
        )
        self._render_decision_added("ADD_COVERED_CODE", item, conflicts)

    def _existing_block_candidates(self, code: CodeTarget) -> list[dict[str, Any]]:
        """Return existing blocks ordered by simple attachment relevance.

        Args:
            code: Code target to attach.

        Returns:
            Candidate blueprint blocks.
        """
        assert self.snapshot is not None
        blocks = [
            block
            for block in self.snapshot.blueprint_data.get("blocks", [])
            if isinstance(block, dict) and block.get("id")
        ]
        code_path = Path(code.path)
        code_parts = set(code_path.parts)

        def score(block: dict[str, Any]) -> tuple[int, str]:
            block_code = block.get("code") if isinstance(block.get("code"), dict) else {}
            block_path = Path(str(block_code.get("path", "")))
            block_parts = set(block_path.parts)
            value = 0
            if block_path == code_path:
                value += 100
            if block_path.parent == code_path.parent:
                value += 40
            if str(block.get("domain") or "") in code_parts:
                value += 20
            value += len(code_parts & block_parts)
            return (-value, str(block.get("id")))

        return sorted(blocks, key=score)[:10]

    def _add_ignore_rule(self, item: DiffItem) -> None:
        """Add an ignore-rule decision for an undeclared code item.

        Args:
            item: Diff item.
        """
        code = item.code_target
        if code is None:
            self.print_func("Cannot ignore because code target is unavailable.")
            return
        self.print_func("")
        self.print_func("IGNORE UNDECLARED CODE")
        self.print_func("")
        self.print_func(f"Target: {code.display_label()}")
        self.print_func("")
        self.print_func("Reason:")
        self.print_func("  [1] local development helper")
        self.print_func("  [2] generated code")
        self.print_func("  [3] example/demo code")
        self.print_func("  [4] temporary experiment")
        self.print_func("  [5] custom reason")
        reason_command = normalize_command(self.input_func("Choice: "))
        reasons = {
            "1": "local development helper",
            "2": "generated code",
            "3": "example/demo code",
            "4": "temporary experiment",
        }
        reason = reasons.get(reason_command)
        if reason_command == "5":
            reason = self.input_func("Custom reason: ").strip() or "custom reason"
        if reason is None:
            return
        request = BlueprintChangeRequest(
            kind=BlueprintChangeKind.ADD_IGNORE_RULE,
            source=BlueprintChangeSource.DIFF,
            payload={
                "rule_data": {
                    "path": code.path,
                    "symbol": code.symbol,
                    "kind": code.kind,
                    "reason": reason,
                }
            },
            human_confirmed=True,
            reason="Diff decision: ignore undeclared code.",
        )
        stamps = collect_file_stamps(self.project_root, [Path("bpfw/blueprint.yaml")])
        conflicts = self.plan.add_authority_action(
            PlannedAuthorityAction(
                diff_item_id=item.identifier,
                label=f"ADD_IGNORE_RULE {code.display_label()}",
                request=request,
                file_stamps=stamps,
            )
        )
        self._render_decision_added("ADD_IGNORE_RULE", item, conflicts)

    def _add_source_delete_action(self, item: DiffItem) -> None:
        """Add a source cleanup candidate to the plan.

        Args:
            item: Diff item.
        """
        code = item.code_target
        if code is None:
            self.print_func("Cannot mark source deletion because code target is unavailable.")
            return
        self.print_func("")
        self.print_func("SOURCE DELETE REVIEW")
        self.print_func("")
        self.print_func(f"Target: {code.display_label()}")
        self.print_func("")
        self.print_func("Warning:")
        self.print_func("  This action modifies source code, not authority files.")
        self.print_func("  Automatic source edits are disabled in this MVP path.")
        self.print_func("")
        self.print_func("Options:")
        self.print_func("  [1] Add cleanup candidate to plan")
        self.print_func("  [2] Cancel")
        command = normalize_command(self.input_func("Choice: "))
        if command != "1":
            return
        action = SourceChangeRequest(
            kind=SourceChangeKind.MARK_FOR_SOURCE_DELETE,
            target=code,
            reason="Diff decision: source cleanup candidate.",
            apply_enabled=False,
        )
        stamps = collect_file_stamps(self.project_root, [Path(code.path)])
        conflicts = self.plan.add_source_action(
            PlannedSourceAction(
                diff_item_id=item.identifier,
                label=f"MARK_FOR_SOURCE_DELETE {code.display_label()}",
                request=action,
                file_stamps=stamps,
            )
        )
        self._render_decision_added("MARK_FOR_SOURCE_DELETE", item, conflicts)

    def _review_missing_declared_code(self, item: DiffItem) -> bool:
        """Review a missing-declared-code item.

        Args:
            item: Diff item.

        Returns:
            True to continue review, False to return home.
        """
        while True:
            self._render_missing_declared_code(item)
            command = normalize_command(self.input_func("Choice: "))
            if is_quit_command(command) or is_back_command(command):
                return False
            if command == "1":
                self.print_func("No-op selected. The finding will remain until code is restored.")
                return True
            if command == "2":
                self._update_to_selected_candidate(item)
                return True
            if command == "3":
                self._remove_declaration(item)
                return True
            if command in {"4", "5"}:
                status = "deprecated" if command == "4" else "legacy"
                self._mark_block_status(item, status)
                return True
            if command == "6":
                self._metadata_for_existing_block(item)
                return True
            if command == "7":
                return True
            self.print_func("Unknown command.")

    def _render_missing_declared_code(self, item: DiffItem) -> None:
        """Render missing-declared-code screen.

        Args:
            item: Diff item.
        """
        target = item.blueprint_target
        self.print_func("")
        self.print_func(f"DIFF: {item.kind.value}")
        self.print_func("")
        self.print_func("BLUEPRINT")
        if target is not None:
            self.print_func(f"  id:        {target.block_id}")
            self.print_func(f"  location:  {target.path}::{target.symbol}")
            self.print_func(f"  lifecycle: {target.status or '<empty>'}")
            self.print_func(f"  purpose:   {target.purpose or '<empty>'}")
        else:
            self.print_func("  Could not resolve blueprint block.")
        self.print_func("")
        self.print_func("CODE")
        self.print_func("  Symbol not found.")
        if item.candidates:
            self.print_func("")
            self.print_func("Possible matches:")
            for index, candidate in enumerate(item.candidates, start=1):
                self.print_func(f"  [{index}] {candidate.display_label()}")
        self.print_func("")
        self.print_func(f"Risk: {item.risk.value}")
        self.print_func(f"Reason: {item.reason}")
        self.print_func("")
        self.print_func("Options:")
        self.print_func("  [1] Keep blueprint as source of truth")
        self.print_func("  [2] Update blueprint to selected match")
        self.print_func("  [3] Remove declaration from blueprint")
        self.print_func("  [4] Mark declaration as deprecated")
        self.print_func("  [5] Mark declaration as legacy")
        self.print_func("  [6] Open inspector metadata window")
        self.print_func("  [7] Skip")
        self.print_func("  [b] Back")
        self.print_func("  [q] Quit")
        self.print_func("")

    def _update_to_selected_candidate(self, item: DiffItem) -> None:
        """Create an update-location decision using a candidate.

        Args:
            item: Diff item.
        """
        target = item.blueprint_target
        if target is None or target.source_shard_path is None:
            self.print_func("Cannot update location because source shard is unavailable.")
            return
        if not item.candidates:
            self.print_func("No candidates available.")
            return
        selected = item.candidates[0]
        self.print_func("")
        self.print_func("UPDATE LOCATION PREVIEW")
        self.print_func("")
        self.print_func(f"Current location: {target.path}::{target.symbol}")
        self.print_func(f"New location:     {selected.display_label()}")
        self.print_func("")
        self.print_func(f"Risk: {item.risk.value}")
        self.print_func("")
        self.print_func("Options:")
        self.print_func("  [1] Add update-location decision to plan")
        self.print_func("  [2] Cancel")
        command = normalize_command(self.input_func("Choice: "))
        if command != "1":
            return
        request = BlueprintChangeRequest(
            kind=BlueprintChangeKind.UPDATE_CODE_REFERENCE,
            source=BlueprintChangeSource.DIFF,
            payload={
                "block_id": target.block_id,
                "source_shard_path": target.source_shard_path,
                "new_path": selected.path,
                "new_symbol": selected.symbol,
                "new_kind": selected.kind,
                "new_name": selected.symbol,
            },
            human_confirmed=True,
            reason="Diff decision: update missing declaration to moved code candidate.",
        )
        stamps = collect_file_stamps(self.project_root, [target.source_shard_path])
        conflicts = self.plan.add_authority_action(
            PlannedAuthorityAction(
                diff_item_id=item.identifier,
                label=f"UPDATE_BLOCK_CODE_REFERENCE {target.block_id}",
                request=request,
                file_stamps=stamps,
            )
        )
        self._render_decision_added("UPDATE_BLOCK_CODE_REFERENCE", item, conflicts)

    def _remove_declaration(self, item: DiffItem) -> None:
        """Add delete-block decision for a missing declaration.

        Args:
            item: Diff item.
        """
        target = item.blueprint_target
        if target is None or target.source_shard_path is None:
            self.print_func("Cannot remove declaration because source shard is unavailable.")
            return
        request = BlueprintChangeRequest(
            kind=BlueprintChangeKind.DELETE_BLOCK,
            source=BlueprintChangeSource.DIFF,
            payload={
                "block_id": target.block_id,
                "source_shard_path": target.source_shard_path,
            },
            human_confirmed=True,
            reason="Diff decision: remove declaration whose code is missing.",
        )
        stamps = collect_file_stamps(self.project_root, [target.source_shard_path])
        conflicts = self.plan.add_authority_action(
            PlannedAuthorityAction(
                diff_item_id=item.identifier,
                label=f"DELETE_BLOCK {target.block_id}",
                request=request,
                file_stamps=stamps,
            )
        )
        self._render_decision_added("DELETE_BLOCK", item, conflicts)

    def _mark_block_status(self, item: DiffItem, status: str) -> None:
        """Add metadata update for block status.

        Args:
            item: Diff item.
            status: New status.
        """
        target = item.blueprint_target
        if target is None or target.source_shard_path is None:
            self.print_func("Cannot update metadata because source shard is unavailable.")
            return
        request = BlueprintChangeRequest(
            kind=BlueprintChangeKind.UPDATE_METADATA,
            source=BlueprintChangeSource.DIFF,
            payload={
                "block_id": target.block_id,
                "source_shard_path": target.source_shard_path,
                "metadata_changes": {"status": status, "lifecycle": status},
            },
            human_confirmed=True,
            reason=f"Diff decision: mark block as {status}.",
        )
        stamps = collect_file_stamps(self.project_root, [target.source_shard_path])
        conflicts = self.plan.add_authority_action(
            PlannedAuthorityAction(
                diff_item_id=item.identifier,
                label=f"UPDATE_BLOCK_METADATA {target.block_id}",
                request=request,
                file_stamps=stamps,
            )
        )
        self._render_decision_added("UPDATE_BLOCK_METADATA", item, conflicts)

    def _metadata_for_existing_block(self, item: DiffItem) -> None:
        """Open metadata window for an existing block and add update action.

        Args:
            item: Diff item.
        """
        target = item.blueprint_target
        if target is None or target.source_shard_path is None:
            self.print_func("Cannot open metadata window because target block is unavailable.")
            return
        draft = run_metadata_window(
            block=target.block_data,
            title="INSPECT METADATA FOR EXISTING BLUEPRINT BLOCK",
            input_func=self.input_func,
            print_func=self.print_func,
        )
        if draft is None:
            return
        changes = draft.metadata_changes()
        if not changes:
            self.print_func("No metadata changes selected.")
            return
        request = BlueprintChangeRequest(
            kind=BlueprintChangeKind.UPDATE_METADATA,
            source=BlueprintChangeSource.DIFF,
            payload={
                "block_id": target.block_id,
                "source_shard_path": target.source_shard_path,
                "metadata_changes": changes,
            },
            human_confirmed=True,
            reason="Diff decision: update existing block metadata.",
        )
        stamps = collect_file_stamps(self.project_root, [target.source_shard_path])
        conflicts = self.plan.add_authority_action(
            PlannedAuthorityAction(
                diff_item_id=item.identifier,
                label=f"UPDATE_BLOCK_METADATA {target.block_id}",
                request=request,
                file_stamps=stamps,
            )
        )
        self._render_decision_added("UPDATE_BLOCK_METADATA", item, conflicts)

    def _review_moved_code_candidate(self, item: DiffItem) -> bool:
        """Review a possible moved-code item.

        Args:
            item: Diff item.

        Returns:
            True to continue, False to return home.
        """
        while True:
            self._render_moved_code_candidate(item)
            command = normalize_command(self.input_func("Choice: "))
            if is_quit_command(command) or is_back_command(command):
                return False
            if command == "1":
                self.print_func("No-op selected. The finding will remain until code is restored or authority changes.")
                return True
            if command == "2":
                self._update_to_selected_candidate(item)
                return True
            if command == "3":
                self._add_candidate_as_new_block(item, status="experimental")
                return True
            if command == "4":
                self._deprecate_old_and_add_candidate(item)
                return True
            if command == "5":
                self._metadata_for_existing_block(item)
                return True
            if command == "6":
                return True
            self.print_func("Unknown command.")

    def _render_moved_code_candidate(self, item: DiffItem) -> None:
        """Render the moved-code candidate decision screen.

        Args:
            item: Diff item.
        """
        target = item.blueprint_target
        candidate = item.code_target or (item.candidates[0] if item.candidates else None)
        self.print_func("")
        self.print_func("DIFF: MOVED_CODE_CANDIDATE")
        self.print_func("")
        self.print_func("BLUEPRINT")
        if target is not None:
            self.print_func(f"  Block:    {target.block_id}")
            self.print_func(f"  Location: {target.path}::{target.symbol}")
            self.print_func(f"  Purpose:  {target.purpose or '<empty>'}")
            self.print_func(f"  Lifecycle:{target.status or '<empty>'}")
        else:
            self.print_func("  Could not resolve blueprint block.")
        self.print_func("")
        self.print_func("CODE CANDIDATE")
        if candidate is not None:
            self.print_func(f"  New location: {candidate.display_label()}")
        else:
            self.print_func("  No candidate available.")
        if item.candidates:
            self.print_func("")
            self.print_func("Possible matches:")
            for index, possible in enumerate(item.candidates, start=1):
                self.print_func(f"  [{index}] {possible.display_label()}")
        self.print_func("")
        self.print_func(f"Risk: {item.risk.value}")
        self.print_func(f"Reason: {item.reason}")
        self.print_func("")
        self.print_func("Options:")
        self.print_func("  [1] Keep blueprint as source of truth")
        self.print_func("  [2] Accept code move and update location")
        self.print_func("  [3] Add candidate as experimental block")
        self.print_func("  [4] Mark old declaration deprecated and add candidate as active")
        self.print_func("  [5] Open inspector metadata window for old block")
        self.print_func("  [6] Skip")
        self.print_func("  [b] Back")
        self.print_func("  [q] Quit")
        self.print_func("")

    def _add_candidate_as_new_block(self, item: DiffItem, status: str) -> None:
        """Add the moved-code candidate as a new block.

        Args:
            item: Diff item.
            status: Status/lifecycle for the new block.
        """
        candidate = item.code_target or (item.candidates[0] if item.candidates else None)
        if candidate is None:
            self.print_func("No candidate available.")
            return
        synthetic = DiffItem(
            identifier=item.identifier,
            kind=DiffItemKind.UNDECLARED_CODE,
            action_level=DiffActionLevel.HUMAN_DECISION,
            risk=item.risk,
            reason=item.reason,
            finding=item.finding,
            code_target=candidate,
        )
        self._quick_create_block(synthetic, status=status)

    def _deprecate_old_and_add_candidate(self, item: DiffItem) -> None:
        """Add a compound move decision: deprecate old block and create new block.

        Args:
            item: Diff item.
        """
        target = item.blueprint_target
        candidate = item.code_target or (item.candidates[0] if item.candidates else None)
        if target is None or target.source_shard_path is None or candidate is None:
            self.print_func("Cannot create compound decision because target data is incomplete.")
            return
        self.print_func("")
        self.print_func("COMPOUND DECISION PREVIEW")
        self.print_func("")
        self.print_func("Actions:")
        self.print_func(f"  1. Mark old block deprecated: {target.block_id}")
        self.print_func(f"  2. Create new active block: {candidate.display_label()}")
        self.print_func("")
        self.print_func("Options:")
        self.print_func("  [1] Add compound decision to plan")
        self.print_func("  [2] Cancel")
        command = normalize_command(self.input_func("Choice: "))
        if command != "1":
            return
        self._mark_block_status(item, "deprecated")
        synthetic = DiffItem(
            identifier=item.identifier,
            kind=DiffItemKind.UNDECLARED_CODE,
            action_level=DiffActionLevel.HUMAN_DECISION,
            risk=item.risk,
            reason=item.reason,
            finding=item.finding,
            code_target=candidate,
        )
        block = self._block_from_code_target(synthetic, status="active")
        if block is None:
            return
        self._add_create_block_action(synthetic, block)

    def _review_duplicate_active_purpose(self, item: DiffItem) -> bool:
        """Review duplicate active purpose item.

        Args:
            item: Diff item.

        Returns:
            True to continue, False to return home.
        """
        while True:
            self._render_duplicate_active_purpose(item)
            command = normalize_command(self.input_func("Choice: "))
            if is_quit_command(command) or is_back_command(command):
                return False
            if command in {"1", "2", "3", "4"}:
                self._resolve_duplicate_by_status(item, command)
                return True
            if command in {"5", "6"}:
                selected_index = 0 if command == "5" else 1
                self._metadata_for_related_block(item, selected_index)
                return True
            if command == "7":
                self._mark_intentional_duplicate(item)
                return True
            if command == "8":
                return True
            self.print_func("Unknown command.")

    def _render_duplicate_active_purpose(self, item: DiffItem) -> None:
        """Render duplicate-active-purpose screen.

        Args:
            item: Diff item.
        """
        purpose = item.finding.evidence.get("purpose") if item.finding is not None else None
        self.print_func("")
        self.print_func("DIFF: DUPLICATE_ACTIVE_PURPOSE")
        self.print_func("")
        self.print_func(f"Purpose: {purpose or '<unknown>'}")
        self.print_func("")
        for index, block in enumerate(item.related_blocks, start=1):
            self.print_func(f"BLOCK {index}")
            self.print_func(f"  id:        {block.block_id}")
            self.print_func(f"  location:  {block.path}::{block.symbol}")
            self.print_func(f"  lifecycle: {block.status or '<empty>'}")
            self.print_func("")
        self.print_func("Options:")
        self.print_func("  [1] Keep A active, mark B experimental")
        self.print_func("  [2] Keep B active, mark A experimental")
        self.print_func("  [3] Keep A active, mark B deprecated")
        self.print_func("  [4] Keep B active, mark A deprecated")
        self.print_func("  [5] Open inspector for A")
        self.print_func("  [6] Open inspector for B")
        self.print_func("  [7] Mark intentional duplicate")
        self.print_func("  [8] Skip")
        self.print_func("  [b] Back")
        self.print_func("  [q] Quit")
        self.print_func("")

    def _resolve_duplicate_by_status(self, item: DiffItem, command: str) -> None:
        """Resolve duplicate active purpose by status update.

        Args:
            item: Diff item.
            command: User command.
        """
        if len(item.related_blocks) < 2:
            self.print_func("Cannot resolve duplicate because related blocks are incomplete.")
            return
        affected_index = 1 if command in {"1", "3"} else 0
        new_status = "experimental" if command in {"1", "2"} else "deprecated"
        synthetic = DiffItem(
            identifier=item.identifier,
            kind=item.kind,
            action_level=item.action_level,
            risk=item.risk,
            reason=item.reason,
            finding=item.finding,
            blueprint_target=item.related_blocks[affected_index],
        )
        self._mark_block_status(synthetic, new_status)

    def _metadata_for_related_block(self, item: DiffItem, selected_index: int) -> None:
        """Open metadata window for a related duplicate block.

        Args:
            item: Diff item.
            selected_index: Zero-based related block index.
        """
        if selected_index >= len(item.related_blocks):
            self.print_func("Selected block is unavailable.")
            return
        synthetic = DiffItem(
            identifier=item.identifier,
            kind=item.kind,
            action_level=item.action_level,
            risk=item.risk,
            reason=item.reason,
            finding=item.finding,
            blueprint_target=item.related_blocks[selected_index],
        )
        self._metadata_for_existing_block(synthetic)

    def _mark_intentional_duplicate(self, item: DiffItem) -> None:
        """Add duplicate-policy metadata to related blocks.

        Args:
            item: Diff item.
        """
        if len(item.related_blocks) < 2:
            self.print_func("Cannot mark duplicate because related blocks are incomplete.")
            return
        self.print_func("")
        self.print_func("INTENTIONAL DUPLICATE REVIEW")
        self.print_func("")
        group_id = self.input_func("Duplicate group id: ").strip()
        reason = self.input_func("Reason: ").strip()
        if not group_id or not reason:
            self.print_func("Duplicate group id and reason are required.")
            return
        for block in item.related_blocks:
            if block.source_shard_path is None:
                continue
            request = BlueprintChangeRequest(
                kind=BlueprintChangeKind.UPDATE_METADATA,
                source=BlueprintChangeSource.DIFF,
                payload={
                    "block_id": block.block_id,
                    "source_shard_path": block.source_shard_path,
                    "metadata_changes": {
                        "duplicate_policy": {
                            "group": group_id,
                            "intentional": True,
                            "reason": reason,
                        }
                    },
                },
                human_confirmed=True,
                reason="Diff decision: mark intentional duplicate.",
            )
            stamps = collect_file_stamps(self.project_root, [block.source_shard_path])
            self.plan.add_authority_action(
                PlannedAuthorityAction(
                    diff_item_id=item.identifier,
                    label=f"UPDATE_DUPLICATE_POLICY {block.block_id}",
                    request=request,
                    file_stamps=stamps,
                )
            )
        self._render_decision_added("UPDATE_DUPLICATE_POLICY", item, self.plan.detect_conflicts())

    def _review_invalid_authority(self, item: DiffItem) -> bool:
        """Review invalid authority item.

        Args:
            item: Diff item.

        Returns:
            True to continue, False to return home.
        """
        self.print_func("")
        self.print_func("DIFF: INVALID_AUTHORITY")
        self.print_func("")
        self.print_func(item.reason)
        if item.finding is not None:
            self.print_func(f"Code: {item.finding.code}")
            if item.finding.path:
                self.print_func(f"Path: {item.finding.path}")
            if item.finding.symbol:
                self.print_func(f"Symbol: {item.finding.symbol}")
        self.print_func("")
        self.print_func("Options:")
        self.print_func("  [1] Open inspector metadata window when a block is available")
        self.print_func("  [2] Skip")
        command = normalize_command(self.input_func("Choice: "))
        if command == "1" and item.blueprint_target is not None:
            self._metadata_for_existing_block(item)
        return True

    def _review_broken_shard_reference(self, item: DiffItem) -> bool:
        """Review broken shard reference item.

        Args:
            item: Diff item.

        Returns:
            True to continue, False to return home.
        """
        self.print_func("")
        self.print_func("DIFF: BROKEN_SHARD_REFERENCE")
        self.print_func("")
        self.print_func(item.reason)
        self.print_func("")
        self.print_func("Options:")
        self.print_func("  [1] Skip")
        self.print_func("  [b] Back")
        command = normalize_command(self.input_func("Choice: "))
        return not is_back_command(command)

    def _review_generic_item(self, item: DiffItem) -> bool:
        """Render an unhandled diff item safely.

        Args:
            item: Diff item.

        Returns:
            True to continue.
        """
        self.print_func("")
        self.print_func(f"DIFF: {item.kind.value}")
        self.print_func("")
        self.print_func(item.reason)
        self.print_func("")
        self.print_func("No automatic decision flow is implemented for this item yet.")
        self.input_func("Press Enter to continue...")
        return True

    def _handle_already_planned(self, item: DiffItem) -> bool:
        """Handle a diff item that already has a plan action.

        Args:
            item: Already planned item.

        Returns:
            True to continue review, False to return home.
        """
        self.print_func("")
        self.print_func("DIFF ALREADY PLANNED")
        self.print_func("")
        self.print_func(f"Diff: {item.kind.value}")
        self.print_func(f"Item: {item.identifier}")
        self.print_func("")
        self.print_func("Options:")
        self.print_func("  [1] Keep existing and continue")
        self.print_func("  [2] Remove planned action and review again")
        self.print_func("  [3] Return home")
        command = normalize_command(self.input_func("Choice: "))
        if command == "2":
            self.plan.remove_actions_for_item(item.identifier)
            self._review_item(item)
        if command == "3":
            return False
        return True

    def _view_plan(self) -> None:
        """Render and handle the apply plan screen."""
        while True:
            self._render_plan()
            command = normalize_command(self.input_func("Choice: "))
            if is_quit_command(command) or is_back_command(command) or command == "r":
                return
            if command == "a":
                self._apply_plan()
                return
            if command == "e":
                self._edit_plan()
                continue
            if command == "c":
                self.plan.clear()
                self.print_func("Plan cleared.")
                continue
            self.print_func("Unknown command.")

    def _render_plan(self) -> None:
        """Render the current apply plan."""
        self.print_func("")
        self.print_func("BPFW DIFF APPLY PLAN")
        self.print_func("")
        if self.plan.is_empty():
            self.print_func("No actions in plan.")
            self.print_func("")
            self.print_func("Options:")
            self.print_func("  [r] Return to review")
            self.print_func("  [q] Quit")
            self.print_func("")
            return
        self.print_func("Authority changes:")
        if not self.plan.authority_actions:
            self.print_func("  none")
        for index, action in enumerate(self.plan.authority_actions, start=1):
            self.print_func(f"  {index}. {action.label}")
        self.print_func("")
        self.print_func("Code changes:")
        if not self.plan.source_actions:
            self.print_func("  none")
        for index, action in enumerate(self.plan.source_actions, start=1):
            self.print_func(f"  {index}. {action.label}")
            if not action.request.apply_enabled:
                self.print_func("     automatic source apply disabled")
        conflicts = self.plan.detect_conflicts()
        stale = self.plan.stale_actions(self.project_root)
        self.print_func("")
        self.print_func("Plan status:")
        self.print_func(f"  conflicts: {len(conflicts)}")
        self.print_func(f"  stale items: {len(stale)}")
        self.print_func("")
        self.print_func("Options:")
        self.print_func("  [a] Apply plan")
        self.print_func("  [e] Edit plan")
        self.print_func("  [r] Return to review")
        self.print_func("  [c] Clear plan")
        self.print_func("  [q] Quit without applying")
        self.print_func("")

    def _edit_plan(self) -> None:
        """Run a minimal plan edit flow."""
        self.print_func("")
        self.print_func("EDIT APPLY PLAN")
        self.print_func("")
        all_item_ids = list(self.plan.planned_item_ids())
        if not all_item_ids:
            self.print_func("No actions to edit.")
            return
        for index, item_id in enumerate(all_item_ids, start=1):
            self.print_func(f"  [{index}] {item_id}")
        self.print_func("")
        self.print_func("Enter an index to remove its actions, or [b] back.")
        command = normalize_command(self.input_func("Choice: "))
        if command.isdigit():
            selected = int(command) - 1
            if 0 <= selected < len(all_item_ids):
                self.plan.remove_actions_for_item(all_item_ids[selected])
                self.print_func("Action removed.")

    def _apply_plan(self) -> None:
        """Apply authority actions after final confirmation."""
        if self.plan.is_empty():
            self.print_func("Plan is empty.")
            return
        conflicts = self.plan.detect_conflicts()
        if conflicts:
            self.print_func("")
            self.print_func("PLAN CONFLICT DETECTED")
            for conflict in conflicts:
                self.print_func(f"  {conflict.message}")
            self.print_func("Resolve conflicts before applying.")
            return
        stale = self.plan.stale_actions(self.project_root)
        if stale:
            self.print_func("")
            self.print_func("PLAN IS STALE")
            self.print_func("")
            self.print_func("Some files changed after decisions were added:")
            for label in stale:
                self.print_func(f"  - {label}")
            self.print_func("")
            self.print_func("Refresh diff and rebuild affected actions before applying.")
            return
        self._render_write_permission_required()
        command = normalize_command(self.input_func("Continue? [y/N]: "))
        if command not in {"y", "yes"}:
            return
        if self.plan.source_actions:
            self.print_func("")
            self.print_func("SOURCE ACTIONS NOT APPLIED")
            self.print_func("Automatic source edits are disabled for this MVP diff path.")
            self.print_func("Authority actions can still be applied.")
        requests = self.plan.authority_requests()
        if not requests:
            self.print_func("No authority actions to apply.")
            return
        preview = self.blueprint_engine.preview_changes(requests)
        if not preview.allowed:
            self.print_func("Plan preview blocked.")
            self.print_func(preview.blocked_reason or "Unknown reason.")
            return
        result = self.blueprint_engine.apply_changes(
            requests,
            write_context=PatchWriteContext(tool_name="diff", allow_guarded_writes=True),
        )
        self.print_func("")
        self.print_func("APPLYING DIFF PLAN")
        self.print_func("")
        if result.success:
            self.print_func("Authority changes applied.")
            report, _exit_code = run_verify(project_root=self.project_root)
            self.print_func("")
            self.print_func("DIFF PLAN APPLIED")
            self.print_func("")
            self.print_func(f"Remaining undeclared code: {report.undeclared_count}")
            self.print_func(f"Remaining missing declared code: {report.missing_declared_count}")
            self.plan.clear()
            self.snapshot = self.review_service.load()
            return
        self.print_func("APPLY FAILED")
        self.print_func(result.blocked_reason or "Unknown apply error.")
        for message in result.messages:
            self.print_func(f"  {message}")

    def _render_write_permission_required(self) -> None:
        """Render final write confirmation."""
        self.print_func("")
        self.print_func("WRITE PERMISSION REQUIRED")
        self.print_func("")
        self.print_func("This operation will modify project files.")
        self.print_func("")
        self.print_func("Authority files:")
        affected_files = self._preview_affected_authority_files()
        if affected_files:
            for path in affected_files:
                self.print_func(f"  - {path}")
        else:
            self.print_func("  none")
        self.print_func("")
        self.print_func("Code files:")
        if self.plan.source_actions:
            for action in self.plan.source_actions:
                self.print_func(f"  - {action.request.target.path} (manual cleanup candidate)")
        else:
            self.print_func("  none")
        self.print_func("")
        self.print_func("No changes have been applied yet.")
        self.print_func("")

    def _preview_affected_authority_files(self) -> tuple[Path, ...]:
        """Preview affected authority files for the current plan.

        Returns:
            Project-relative authority files.
        """
        if not self.plan.authority_actions:
            return ()
        preview = self.blueprint_engine.preview_changes(self.plan.authority_requests())
        return preview.affected_files

    def _handle_quit(self) -> int:
        """Handle quit when the plan may contain unapplied decisions.

        Returns:
            Process exit code.
        """
        if self.plan.is_empty():
            self.print_func("Diff closed.")
            return 0
        self.print_func("")
        self.print_func("QUIT DIFF SESSION")
        self.print_func("")
        self.print_func("You have unapplied decisions.")
        self.print_func(f"Pending actions: {self.plan.action_count()}")
        self.print_func("")
        self.print_func("Options:")
        self.print_func("  [1] Apply plan now")
        self.print_func("  [2] Discard plan and quit")
        self.print_func("  [3] Return to diff")
        command = normalize_command(self.input_func("Choice: "))
        if command == "1":
            self._apply_plan()
            return 0
        if command == "3":
            return self.run()
        self.print_func("Plan discarded.")
        return 0

    def _render_decision_added(self, action_label: str, item: DiffItem, conflicts: list[Any]) -> None:
        """Render the decision-added screen.

        Args:
            action_label: Action label.
            item: Diff item.
            conflicts: Conflicts detected after adding.
        """
        self.print_func("")
        self.print_func("DECISION ADDED TO PLAN")
        self.print_func("")
        self.print_func(f"Action: {action_label}")
        if item.code_target is not None:
            self.print_func(f"Target: {item.code_target.display_label()}")
        if item.blueprint_target is not None:
            self.print_func(f"Block:  {item.blueprint_target.block_id}")
        self.print_func("")
        self.print_func("No files modified yet.")
        if conflicts:
            self.print_func("")
            self.print_func("Plan conflicts detected:")
            for conflict in conflicts:
                self.print_func(f"  - {conflict.message}")
        self.print_func("")
        self.print_func("Options:")
        self.print_func("  [Enter] Next diff")
        self.print_func("  [p] View apply plan")
        self.print_func("  [u] Undo this decision")
        command = normalize_command(self.input_func("Choice: "))
        if command == "p":
            self._view_plan()
        elif command == "u":
            self.plan.remove_actions_for_item(item.identifier)
            self.print_func("Decision removed from plan.")

    def _block_from_code_target(self, item: DiffItem, status: str) -> dict[str, Any] | None:
        """Build a block dictionary from an undeclared code target.

        Args:
            item: Diff item.
            status: Status/lifecycle value.

        Returns:
            Block data, or None when code target is missing.
        """
        code = item.code_target
        if code is None:
            return None
        unit = _unit_like_from_code_target(code)
        block = build_new_detected_responsibility(unit)
        block["id"] = self._unique_block_id(block)
        block["status"] = status
        apply_suggestions(block)
        if not block.get("status"):
            block["status"] = status
        return block

    def _unique_block_id(self, block: dict[str, Any]) -> str:
        """Return a block id that does not already exist in the snapshot.

        Args:
            block: Candidate block dictionary.

        Returns:
            Unique block identifier.
        """
        assert self.snapshot is not None
        blocks = self.snapshot.blueprint_data.get("blocks", [])
        existing_ids = {
            str(existing.get("id"))
            for existing in blocks
            if isinstance(existing, dict) and existing.get("id")
        }
        code = block.get("code") if isinstance(block.get("code"), dict) else {}
        module = str(code.get("module", ""))
        symbol = str(code.get("symbol", ""))
        base_id = to_snake_case(f"{module}_{symbol}") or to_snake_case(symbol) or "new_block"
        if base_id not in existing_ids:
            return base_id
        sequence = 2
        while f"{base_id}_{sequence}" in existing_ids:
            sequence += 1
        return f"{base_id}_{sequence}"

    def _group_counts(self) -> dict[str, int]:
        """Return item counts by group.

        Returns:
            Mapping of action level to count.
        """
        assert self.snapshot is not None
        counts: dict[str, int] = {}
        for item in self.snapshot.items:
            counts[item.action_level.value] = counts.get(item.action_level.value, 0) + 1
        return counts

    def _ordered_group_values(self) -> list[str]:
        """Return diff groups in stable display order.

        Returns:
            Ordered group names.
        """
        assert self.snapshot is not None
        counts = self._group_counts()
        order = [
            DiffActionLevel.SAFE_MECHANICAL_UPDATE.value,
            DiffActionLevel.HUMAN_DECISION.value,
            DiffActionLevel.READ_ONLY.value,
        ]
        return [name for name in order if counts.get(name, 0) > 0]


class _UnitLike:
    """Minimal object compatible with inspector block creation helpers."""

    def __init__(self, code: CodeTarget) -> None:
        """Initialize from a code target.

        Args:
            code: Code target.
        """
        self.path = code.path
        self.module = _module_from_path(code.path)
        self.symbol = code.symbol
        self.symbol_type = code.kind
        self.qualified_name = code.qualified_name or f"{self.module}.{code.symbol}"
        self.start_line = code.start_line
        self.end_line = code.end_line
        self.methods: list[str] = []
        self.functions: list[str] = []
        self.imports: list[str] = []
        self.decorators: list[str] = []
        self.docstring = None
        self.signature = None
        self.interface_inputs: list[dict[str, Any]] = []
        self.interface_output = None
        self.calls: list[dict[str, Any]] = []


def _unit_like_from_code_target(code: CodeTarget) -> _UnitLike:
    """Return a minimal scanner-unit adapter.

    Args:
        code: Code target.

    Returns:
        Unit-like object.
    """
    return _UnitLike(code)


def _module_from_path(path_value: str) -> str:
    """Derive a dotted module path from a source path.

    Args:
        path_value: Project-relative source path.

    Returns:
        Dotted module name.
    """
    path = Path(path_value)
    parts = list(path.with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts)
