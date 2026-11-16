"""Terminal rendering for Drift Gate decision screens.

Rendering is intentionally isolated from decision semantics and authority writes.
The renderer receives already-computed capabilities and only formats output.
"""

from __future__ import annotations

from collections.abc import Callable

from bpfw.integrations.diff.models import DiffItem
from bpfw.integrations.diff.package_moves import PackageMoveGroup
from bpfw.integrations.inspector.drift_gate_helpers import (
    BOX_INNER_WIDTH,
    DRIFT_GATE_WIDTH,
    target_block_id,
    target_location,
    wrap_operation_box_text,
)
from bpfw.integrations.inspector.drift_gate_models import DriftGateResult
from bpfw.integrations.shared.cli_explorer.presentation import safe, width, terminal_width, wrap_text

PrintFunc = Callable[[str], None]
CanGoBack = Callable[[], bool]


class DriftGateRenderer:
    """Render Drift Gate screens without interpreting commands or mutating authority."""

    def __init__(self, print_func: PrintFunc, result: DriftGateResult, can_go_back: CanGoBack) -> None:
        self.print_func = print_func
        self.result = result
        self.can_go_back = can_go_back
        self._buffer_active = False

    def _buffered(self, render_body: Callable[[], None]) -> None:
        if self._buffer_active:
            render_body()
            return
        original = self.print_func
        lines: list[str] = []
        self._buffer_active = True
        self.print_func = lambda line: lines.append(str(line))
        try:
            render_body()
        finally:
            self.print_func = original
            self._buffer_active = False
        if lines:
            original("\n".join(lines))

    def _cache_notice(self) -> None:
        if self.result.cache_hit:
            for line in wrap_text("Cache: loaded pending drift snapshot; full scan/verify was skipped.",self._screen_width()):
                self.print_func(line)

    def _screen_width(self) -> int:
        """Use terminal width, not the historical fixed 80-column decision box."""
        return min(DRIFT_GATE_WIDTH, terminal_width())

    def _screen_header(self, index: int, total: int, risk: str, subtitle: str | None = None) -> None:
        w=self._screen_width()
        left=f'Decision {index} of {total}'
        right=f'Risk: {safe(risk)}'
        source='cached pending drift snapshot' if self.result.cache_hit else 'current drift analysis'
        self.print_func('')
        self.print_func('BPFW DRIFT GATE')
        self.print_func('='*w)
        if width(left)+width(right)+2<=w:
            self.print_func(left+' '*(w-width(left)-width(right))+right)
        else:
            self.print_func(left)
            self.print_func(right)
        for line in wrap_text('Source: '+source,w):self.print_func(line)
        self._cache_notice()
        if subtitle:self.print_func(safe(subtitle))
        self.print_func('')

    def _box_line(self, text: str) -> None:
        capacity=max(1,self._screen_width()-4)
        for line in wrap_text(text,capacity):
            self.print_func('| '+line+' '*max(0,capacity-width(line))+' |')

    def _operation_box(self, title: str, lines: list[str]) -> None:
        w=self._screen_width()
        self.print_func('+'+'-'*(w-2)+'+')
        self._box_line('OPERATION UNDER REVIEW: '+title)
        for line in lines:self._box_line(line)
        self.print_func('+'+'-'*(w-2)+'+')
        self.print_func('')

    def _progress_footer(self, index: int, total: int) -> None:
        self.print_func("Progress after this:")
        self.print_func(f"  decisions left:       {max(total - index, 0)}")
        self.print_func(f"  inspector candidates: {len(self.result.inspector_issues)}")

    def package_move(self, group: PackageMoveGroup, index: int, total: int) -> None:
        self._buffered(lambda: self._package_move_body(group, index, total))

    def _package_move_body(self, group: PackageMoveGroup, index: int, total: int) -> None:
        self._screen_header(index=index, total=total, risk="MEDIUM")
        self._operation_box(
            title="PACKAGE MOVE",
            lines=[
                "",
                f"  Before: {group.old_prefix}",
                f"  After:  {group.new_prefix}",
                "",
                f"  Affected declarations: {len(group.items)}",
            ],
        )
        self.print_func("BPFW found a package move.")
        self.print_func("")
        self.print_func("Choose how to handle this move:")
        self.print_func("")
        self.print_func("  [1] Accept this package move")
        self.print_func(f"      Update all {len(group.items)} declarations automatically.")
        self.print_func("")
        self.print_func("  [2] Review each declaration")
        self.print_func("      Safer, but slower.")
        self.print_func("")
        self.print_func("  [3] Reject this move")
        self.print_func("      Keep blueprint as source of truth. Code must be restored later.")
        self.print_func("")
        self.print_func("  [s] Skip for now")
        if self.can_go_back():
            self.print_func("  [b] Back")
        self.print_func("  [q] Quit")
        self.print_func("")
        self.print_func("Evidence:")
        self.print_func(f"  same relative path: {len(group.items)}")
        self.print_func(f"  same symbol:        {len(group.items)}")
        self.print_func(f"  same kind:          {len(group.items)}")
        self.print_func("  fingerprint:        partial or unavailable")

    def undeclared_code(
        self,
        item: DiffItem,
        index: int,
        total: int,
        available_commands: set[str],
    ) -> None:
        self._buffered(lambda: self._undeclared_code_body(item, index, total, available_commands))

    def _undeclared_code_body(self, item: DiffItem, index: int, total: int, available_commands: set[str]) -> None:
        code = item.code_target
        operation_lines = [""]
        if code is not None:
            operation_lines.extend([f"  New code: {code.display_label()}", "", f"  Kind: {code.kind}"])
            if code.start_line is not None and code.end_line is not None:
                operation_lines.append(f"  Lines: {code.start_line}-{code.end_line}")
        else:
            operation_lines.append("  New code: unavailable")
        self._screen_header(index=index, total=total, risk=item.risk.value)
        self._operation_box(title="NEW UNDECLARED CODE", lines=operation_lines)
        self.print_func("BPFW found code that is not declared in blueprint.")
        self.print_func("")
        self.print_func("What is this code?")
        options = {
            "1": ("A real active responsibility", "Add it to Inspector for metadata completion."),
            "2": ("Experimental code", "Add it, but not as the main active path."),
            "3": ("Part of an existing responsibility", "Attach it to another declared block."),
            "4": ("Internal/helper code", "Ignore it."),
            "5": ("Code that should not exist", "Reject it."),
        }
        for command, (title, help_text) in options.items():
            if command in available_commands:
                self.print_func("")
                self.print_func(f"  [{command}] {title}")
                self.print_func(f"      {help_text}")
        self.print_func("")
        self.print_func("  [s] Skip for now")
        if "b" in available_commands:
            self.print_func("  [b] Back")
        self.print_func("  [q] Quit")
        self.print_func("")
        self._progress_footer(index=index, total=total)
        self.print_func("")
        self.print_func("Evidence:")
        if code is not None:
            self.print_func(f"  Kind: {code.kind}")
            if code.start_line is not None and code.end_line is not None:
                self.print_func(f"  Lines: {code.start_line}-{code.end_line}")
        self.print_func(f"  Risk: {item.risk.value}")
        self.print_func("  Fingerprint: available")
        self.print_func("  Source: scanner")

    def missing_or_moved(self, item: DiffItem, index: int, total: int, available_commands: set[str]) -> None:
        self._buffered(lambda: self._missing_or_moved_body(item, index, total, available_commands))

    def _missing_or_moved_body(self, item: DiffItem, index: int, total: int, available_commands: set[str]) -> None:
        target = item.blueprint_target
        candidate = item.code_target or (item.candidates[0] if item.candidates else None)
        if candidate is None:
            title = "MISSING DECLARED CODE"
            lines = ["", f"  Blueprint: {target_location(target)}", "  Codebase:  NOT FOUND", "", f"  Declaration ID: {target_block_id(target)}"]
        else:
            title = "POSSIBLE MOVED OR RENAMED CODE"
            lines = ["", f"  Before: {target_location(target)}", f"  After:  {candidate.display_label()}", "", "  Match confidence: weak"]
        self._screen_header(index=index, total=total, risk=item.risk.value)
        self._operation_box(title=title, lines=lines)
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
            if "2" in available_commands:
                self.print_func("")
                self.print_func("  [2] This is the same responsibility")
                self.print_func("      Update blueprint to the new location.")
            if "3" in available_commands:
                self.print_func("")
                self.print_func("  [3] This is different experimental code")
                self.print_func("      Add candidate as experimental responsibility.")
        lifecycle_options = {
            "4": ("Old declaration is deprecated", "Keep the old declaration, but mark it deprecated."),
            "5": ("Old declaration is legacy", "Keep the old declaration as legacy authority."),
            "6": ("Old declaration should be removed", "Delete the old declaration from blueprint."),
        }
        for command, (title_text, help_text) in lifecycle_options.items():
            if command in available_commands:
                self.print_func("")
                self.print_func(f"  [{command}] {title_text}")
                self.print_func(f"      {help_text}")
        self.print_func("")
        self.print_func("  [s] Skip for now")
        if "b" in available_commands:
            self.print_func("  [b] Back")
        self.print_func("  [q] Quit")
        self.print_func("")
        self._progress_footer(index=index, total=total)
        self.print_func("")
        self.print_func("Evidence:")
        if target is not None:
            self.print_func(f"  declared kind: {target.kind or '-'}")
        self.print_func("  Current code: missing" if candidate is None else "  Candidate evidence: weak match")
        self.print_func(f"  risk: {item.risk.value}")

    def duplicate_active_purpose(self, item: DiffItem, index: int, total: int) -> None:
        self._buffered(lambda: self._duplicate_active_purpose_body(item, index, total))

    def _duplicate_active_purpose_body(self, item: DiffItem, index: int, total: int) -> None:
        purpose = item.finding.evidence.get("purpose") if item.finding is not None else None
        operation_lines = ["", f"  Purpose: {purpose or '-'}", ""]
        for label, block in zip(("A", "B"), item.related_blocks):
            operation_lines.extend([f"  {label}: {block.display_label()}", f"     lifecycle: {block.status or '-'}", ""])
        self._screen_header(index=index, total=total, risk=item.risk.value)
        self._operation_box(title="DUPLICATE ACTIVE PURPOSE", lines=operation_lines)
        lines = [
            "Two active blocks declare the same purpose.", "",
            "Only one should remain active unless this duplicate is intentional.", "",
            "What should BPFW do?", "",
            "  [1] Keep A active, mark B experimental", "      A remains the main implementation. B is kept for review.", "",
            "  [2] Keep B active, mark A experimental", "      B becomes the main implementation. A is kept for review.", "",
            "  [3] Keep A active, mark B deprecated", "      A remains active. B is marked as no longer preferred.", "",
            "  [4] Keep B active, mark A deprecated", "      B remains active. A is marked as no longer preferred.", "",
            "  [5] This duplicate is intentional", "      Keep both, but require explicit authority metadata.", "",
            "  [6] Send A to Inspector", "      Review A before deciding.", "",
            "  [7] Send B to Inspector", "      Review B before deciding.", "",
            "  [s] Skip for now",
        ]
        if self.can_go_back():
            lines.append("  [b] Back")
        lines.extend(["  [q] Quit", "", "Rule:", "  BPFW never allows duplicate active purposes silently."])
        for line in lines:
            self.print_func(line)

    def generic(self, item: DiffItem, index: int, total: int) -> None:
        self._buffered(lambda: self._generic_body(item, index, total))

    def _generic_body(self, item: DiffItem, index: int, total: int) -> None:
        self._screen_header(index=index, total=total, risk=item.risk.value)
        self._operation_box(title="STRUCTURAL DRIFT", lines=["", f"  Type: {item.kind.value}", "", f"  {item.reason}"])
        self.print_func("BPFW found structural drift that needs manual review.")
        self.print_func("")
        self.print_func("Available actions:")
        self.print_func("")
        self.print_func("  [s] Skip for now")
        if self.can_go_back():
            self.print_func("  [b] Back")
        self.print_func("  [q] Quit")
        self.print_func("")
