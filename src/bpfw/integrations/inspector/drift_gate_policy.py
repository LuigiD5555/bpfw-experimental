"""Pure decision policy for Drift Gate review screens.

The runner owns interaction and side effects. This module owns only the rules
that decide whether an item requires human review and which commands are valid
for the current evidence. Keeping these rules pure makes menu rendering and
command handling share one testable source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass

from bpfw.integrations.diff.models import DiffItemKind


_METADATA_ONLY_KINDS = frozenset({
    DiffItemKind.INCOMPLETE_METADATA,
    DiffItemKind.METADATA_DRIFT,
})


@dataclass(frozen=True, slots=True)
class MissingOrMovedCapabilities:
    """Evidence-derived capabilities for a missing/moved-code decision."""

    candidate_available: bool
    target_writable: bool
    can_go_back: bool = False


@dataclass(frozen=True, slots=True)
class UndeclaredCapabilities:
    """Evidence-derived capabilities for an undeclared-code decision."""

    code_target_available: bool
    existing_responsibilities_available: bool
    can_go_back: bool = False


class DriftDecisionPolicy:
    """Central source of truth for Drift Gate command availability."""

    @staticmethod
    def requires_human_decision(kind: DiffItemKind) -> bool:
        """Return whether a diff kind is structural and needs Drift Gate review."""
        return kind not in _METADATA_ONLY_KINDS

    @staticmethod
    def undeclared_commands(capabilities: UndeclaredCapabilities) -> set[str]:
        """Return commands valid for an undeclared-code review."""
        commands = {"s", "q"}
        if capabilities.can_go_back:
            commands.add("b")
        if not capabilities.code_target_available:
            return commands
        commands.update({"1", "2", "4", "5"})
        if capabilities.existing_responsibilities_available:
            commands.add("3")
        return commands

    @staticmethod
    def missing_or_moved_commands(capabilities: MissingOrMovedCapabilities) -> set[str]:
        """Return commands valid for a missing/moved-code review."""
        commands = {"1", "s", "q"}
        if capabilities.can_go_back:
            commands.add("b")
        if capabilities.candidate_available and capabilities.target_writable:
            commands.add("2")
        if capabilities.candidate_available:
            commands.add("3")
        if capabilities.target_writable:
            commands.update({"4", "5", "6"})
        return commands
