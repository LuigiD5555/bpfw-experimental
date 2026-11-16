"""Pure command interpretation for Drift Gate decision screens.

Terminal rendering and side effects intentionally live elsewhere.  These
functions translate normalized user input plus currently valid capabilities
into explicit decision intents that can be unit-tested without a terminal.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from bpfw.integrations.shared.cli_runtime import is_quit_command


class DriftDecisionIntent(str, Enum):
    """Semantic intent represented by one Drift Gate command."""

    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    QUIT = "quit"
    BACK = "back"
    BACK_UNAVAILABLE = "back_unavailable"
    SKIP = "skip"

    PACKAGE_ACCEPT_MOVE = "package_accept_move"
    PACKAGE_REVIEW_INDIVIDUAL = "package_review_individual"
    PACKAGE_KEEP_BLUEPRINT = "package_keep_blueprint"

    UNDECLARED_APPROVE_ACTIVE = "undeclared_approve_active"
    UNDECLARED_APPROVE_EXPERIMENTAL = "undeclared_approve_experimental"
    UNDECLARED_ATTACH = "undeclared_attach"
    UNDECLARED_IGNORE = "undeclared_ignore"
    UNDECLARED_REJECT = "undeclared_reject"

    MISSING_KEEP_BLUEPRINT = "missing_keep_blueprint"
    MISSING_ACCEPT_CANDIDATE = "missing_accept_candidate"
    MISSING_APPROVE_EXPERIMENTAL = "missing_approve_experimental"
    MISSING_MARK_DEPRECATED = "missing_mark_deprecated"
    MISSING_MARK_LEGACY = "missing_mark_legacy"
    MISSING_REMOVE_DECLARATION = "missing_remove_declaration"

    DUPLICATE_KEEP_A_MARK_B_EXPERIMENTAL = "duplicate_keep_a_mark_b_experimental"
    DUPLICATE_KEEP_B_MARK_A_EXPERIMENTAL = "duplicate_keep_b_mark_a_experimental"
    DUPLICATE_KEEP_A_MARK_B_DEPRECATED = "duplicate_keep_a_mark_b_deprecated"
    DUPLICATE_KEEP_B_MARK_A_DEPRECATED = "duplicate_keep_b_mark_a_deprecated"
    DUPLICATE_MARK_INTENTIONAL = "duplicate_mark_intentional"
    DUPLICATE_INSPECT_A = "duplicate_inspect_a"
    DUPLICATE_INSPECT_B = "duplicate_inspect_b"


@dataclass(frozen=True, slots=True)
class DriftDecisionCommand:
    """Parsed decision command independent from terminal interaction."""

    intent: DriftDecisionIntent
    raw: str

    @property
    def is_terminal_control(self) -> bool:
        """Return whether the command changes navigation rather than domain state."""
        return self.intent in {
            DriftDecisionIntent.QUIT,
            DriftDecisionIntent.BACK,
            DriftDecisionIntent.BACK_UNAVAILABLE,
            DriftDecisionIntent.SKIP,
            DriftDecisionIntent.UNKNOWN,
            DriftDecisionIntent.UNAVAILABLE,
        }


class DriftDecisionEngine:
    """Translate normalized Drift Gate commands into semantic intents."""

    _PACKAGE = {
        "1": DriftDecisionIntent.PACKAGE_ACCEPT_MOVE,
        "2": DriftDecisionIntent.PACKAGE_REVIEW_INDIVIDUAL,
        "3": DriftDecisionIntent.PACKAGE_KEEP_BLUEPRINT,
    }
    _UNDECLARED = {
        "1": DriftDecisionIntent.UNDECLARED_APPROVE_ACTIVE,
        "2": DriftDecisionIntent.UNDECLARED_APPROVE_EXPERIMENTAL,
        "3": DriftDecisionIntent.UNDECLARED_ATTACH,
        "4": DriftDecisionIntent.UNDECLARED_IGNORE,
        "5": DriftDecisionIntent.UNDECLARED_REJECT,
    }
    _MISSING = {
        "1": DriftDecisionIntent.MISSING_KEEP_BLUEPRINT,
        "2": DriftDecisionIntent.MISSING_ACCEPT_CANDIDATE,
        "3": DriftDecisionIntent.MISSING_APPROVE_EXPERIMENTAL,
        "4": DriftDecisionIntent.MISSING_MARK_DEPRECATED,
        "5": DriftDecisionIntent.MISSING_MARK_LEGACY,
        "6": DriftDecisionIntent.MISSING_REMOVE_DECLARATION,
    }
    _DUPLICATE = {
        "1": DriftDecisionIntent.DUPLICATE_KEEP_A_MARK_B_EXPERIMENTAL,
        "2": DriftDecisionIntent.DUPLICATE_KEEP_B_MARK_A_EXPERIMENTAL,
        "3": DriftDecisionIntent.DUPLICATE_KEEP_A_MARK_B_DEPRECATED,
        "4": DriftDecisionIntent.DUPLICATE_KEEP_B_MARK_A_DEPRECATED,
        "5": DriftDecisionIntent.DUPLICATE_MARK_INTENTIONAL,
        "6": DriftDecisionIntent.DUPLICATE_INSPECT_A,
        "7": DriftDecisionIntent.DUPLICATE_INSPECT_B,
    }

    @staticmethod
    def _common(command: str, *, can_go_back: bool) -> DriftDecisionCommand | None:
        if is_quit_command(command):
            return DriftDecisionCommand(DriftDecisionIntent.QUIT, command)
        if command == "b":
            intent = DriftDecisionIntent.BACK if can_go_back else DriftDecisionIntent.BACK_UNAVAILABLE
            return DriftDecisionCommand(intent, command)
        if command == "s":
            return DriftDecisionCommand(DriftDecisionIntent.SKIP, command)
        return None

    @classmethod
    def package(cls, command: str, *, can_go_back: bool) -> DriftDecisionCommand:
        common = cls._common(command, can_go_back=can_go_back)
        if common is not None:
            return common
        return DriftDecisionCommand(cls._PACKAGE.get(command, DriftDecisionIntent.UNKNOWN), command)

    @classmethod
    def undeclared(
        cls,
        command: str,
        *,
        available_commands: set[str],
        can_go_back: bool,
    ) -> DriftDecisionCommand:
        common = cls._common(command, can_go_back=can_go_back)
        if common is not None:
            if common.intent == DriftDecisionIntent.BACK:
                if "b" not in available_commands:
                    return DriftDecisionCommand(DriftDecisionIntent.BACK_UNAVAILABLE, command)
                return common
            if common.intent in {
                DriftDecisionIntent.SKIP,
                DriftDecisionIntent.QUIT,
                DriftDecisionIntent.BACK_UNAVAILABLE,
            }:
                return common
        if command not in available_commands:
            known = command in cls._UNDECLARED or command in {"b", "s", "q"}
            return DriftDecisionCommand(
                DriftDecisionIntent.UNAVAILABLE if known else DriftDecisionIntent.UNKNOWN,
                command,
            )
        return DriftDecisionCommand(cls._UNDECLARED.get(command, DriftDecisionIntent.UNKNOWN), command)

    @classmethod
    def missing_or_moved(
        cls,
        command: str,
        *,
        available_commands: set[str],
        can_go_back: bool,
    ) -> DriftDecisionCommand:
        common = cls._common(command, can_go_back=can_go_back)
        if common is not None:
            if common.intent == DriftDecisionIntent.BACK:
                if "b" not in available_commands:
                    return DriftDecisionCommand(DriftDecisionIntent.BACK_UNAVAILABLE, command)
                return common
            if common.intent in {
                DriftDecisionIntent.SKIP,
                DriftDecisionIntent.QUIT,
                DriftDecisionIntent.BACK_UNAVAILABLE,
            }:
                return common
        if command not in available_commands:
            known = command in cls._MISSING or command in {"b", "s", "q"}
            return DriftDecisionCommand(
                DriftDecisionIntent.UNAVAILABLE if known else DriftDecisionIntent.UNKNOWN,
                command,
            )
        return DriftDecisionCommand(cls._MISSING.get(command, DriftDecisionIntent.UNKNOWN), command)

    @classmethod
    def duplicate(cls, command: str, *, can_go_back: bool, block_count: int) -> DriftDecisionCommand:
        common = cls._common(command, can_go_back=can_go_back)
        if common is not None:
            return common
        intent = cls._DUPLICATE.get(command)
        if intent is None:
            return DriftDecisionCommand(DriftDecisionIntent.UNKNOWN, command)
        if block_count < 2 and command in {"1", "2", "3", "4", "6", "7"}:
            return DriftDecisionCommand(DriftDecisionIntent.UNAVAILABLE, command)
        return DriftDecisionCommand(intent, command)

    @classmethod
    def generic(cls, command: str, *, can_go_back: bool) -> DriftDecisionCommand:
        common = cls._common(command, can_go_back=can_go_back)
        if common is not None:
            return common
        return DriftDecisionCommand(DriftDecisionIntent.UNKNOWN, command)
