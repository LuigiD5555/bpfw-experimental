"""Data models for the authority Blueprint Engine.

These models describe approved authority changes. They are intentionally
separate from drift findings: findings detect problems, while change requests
express what an authorized tool wants the engine to modify under ``bpfw/``.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from bpfw.authority.patch.result import AuthorityPatchResult


class BlueprintChangeKind(Enum):
    """Stable labels for supported Blueprint Engine change requests."""

    CREATE_BLOCK = "create_block"
    DELETE_BLOCK = "delete_block"
    UPDATE_METADATA = "update_metadata"
    UPDATE_LOCATION = "update_location"
    UPDATE_SYMBOL = "update_symbol"
    UPDATE_CODE_REFERENCE = "update_code_reference"
    MOVE_BLOCK = "move_block"
    CREATE_SHARD = "create_shard"
    DELETE_SHARD = "delete_shard"
    RENAME_SHARD = "rename_shard"
    MOVE_SHARD = "move_shard"
    ADD_IGNORE_RULE = "add_ignore_rule"
    REMOVE_IGNORE_RULE = "remove_ignore_rule"
    ADD_COVERED_CODE = "add_covered_code"
    REMOVE_COVERED_CODE = "remove_covered_code"


class BlueprintChangeSource(Enum):
    """Origin of a Blueprint Engine change request."""

    INSPECTOR = "inspector"
    EDITOR = "editor"
    PLANNER = "planner"
    SAFE_MECHANICAL_UPDATE = "safe_mechanical_update"
    CONTROLLED_REFACTOR = "controlled_refactor"
    DIFF = "diff"
    TEST = "test"


@dataclass(frozen=True)
class MechanicalChangeEvidence:
    """Evidence required for automatic mechanical updates.

    Attributes:
        exact_content_match: Whether the old and new code fingerprints match.
        one_to_one_match: Whether exactly one old block maps to one new candidate.
        symbol_kind_matches: Whether both sides are the same symbol kind.
        purpose_preserved: Whether authority purpose is not being changed.
        dangerous_capability_added: Whether the new candidate introduces risky capabilities.
        competing_candidates: Number of competing candidates detected.
        description: Human-readable reason or hash summary.
    """

    exact_content_match: bool = False
    one_to_one_match: bool = False
    symbol_kind_matches: bool = False
    purpose_preserved: bool = False
    dangerous_capability_added: bool = False
    competing_candidates: int = 0
    description: str | None = None

    def is_safe_mechanical_match(self) -> bool:
        """Return whether evidence allows an automatic mechanical update.

        Returns:
            True when the evidence satisfies all safe-update requirements.
        """
        return (
            self.exact_content_match
            and self.one_to_one_match
            and self.symbol_kind_matches
            and self.purpose_preserved
            and not self.dangerous_capability_added
            and self.competing_candidates == 0
        )


@dataclass(frozen=True)
class BlueprintChangeRequest:
    """Approved or candidate request to modify BPFW authority files.

    Attributes:
        kind: Mechanical change kind.
        source: Tool or workflow that produced the request.
        payload: Operation-specific data used to build a patch plan.
        human_confirmed: Whether a human explicitly approved the change.
        mechanical_evidence: Evidence for no-confirmation mechanical updates.
        reason: Optional human-readable reason for audit output.
    """

    kind: BlueprintChangeKind
    source: BlueprintChangeSource
    payload: dict[str, Any] = field(default_factory=dict)
    human_confirmed: bool = False
    mechanical_evidence: MechanicalChangeEvidence | None = None
    reason: str | None = None


@dataclass(frozen=True)
class BlueprintChangePreview:
    """Read-only preview of a Blueprint Engine change request.

    Attributes:
        allowed: Whether the request can be applied.
        operation_count: Number of patch operations that would run.
        affected_files: Project-relative files that would be modified.
        messages: Human-readable preview and validation messages.
        blocked_reason: Reason the preview is blocked, if any.
    """

    allowed: bool
    operation_count: int = 0
    affected_files: tuple[Path, ...] = ()
    messages: tuple[str, ...] = ()
    blocked_reason: str | None = None


@dataclass
class BlueprintChangeResult:
    """Result returned by Blueprint Engine apply methods.

    Attributes:
        success: Whether the change applied successfully.
        patch_result: Low-level patch result returned by the patch engine.
        messages: Human-readable result messages.
        blocked_reason: Reason the change was blocked before patching, if any.
    """

    success: bool = False
    patch_result: AuthorityPatchResult | None = None
    messages: list[str] = field(default_factory=list)
    blocked_reason: str | None = None
