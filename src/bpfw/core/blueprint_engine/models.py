"""PURPOSE data models for the authority Blueprint Engine
DOMAIN  approved blueprint changes
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from bpfw.core.authority.patch.result import AuthorityPatchResult


class BlueprintChangeKind(Enum):
    """PURPOSE stable labels for supported Blueprint Engine change requests
    DOMAIN  approved blueprint changes
    """

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
    """PURPOSE origin of a Blueprint Engine change request
    DOMAIN  approved blueprint changes
    """

    INSPECTOR = "inspector"
    EDITOR = "editor"
    PLANNER = "planner"
    SAFE_MECHANICAL_UPDATE = "safe_mechanical_update"
    CONTROLLED_REFACTOR = "controlled_refactor"
    DIFF = "diff"
    TEST = "test"


@dataclass(frozen=True)
class MechanicalChangeEvidence:
    """PURPOSE evidence required for automatic safe file updates
        DOMAIN  approved blueprint changes
        """

    exact_content_match: bool = False
    one_to_one_match: bool = False
    symbol_kind_matches: bool = False
    purpose_preserved: bool = False
    dangerous_capability_added: bool = False
    competing_candidates: int = 0
    description: str | None = None

    def is_safe_mechanical_match(self) -> bool:
        """PURPOSE check whether evidence allows an automatic safe file update
                DOMAIN  approved blueprint changes
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
    """PURPOSE approved or candidate request to modify BPFW authority files
    DOMAIN  approved blueprint changes
    """

    kind: BlueprintChangeKind
    source: BlueprintChangeSource
    payload: dict[str, Any] = field(default_factory=dict)
    human_confirmed: bool = False
    mechanical_evidence: MechanicalChangeEvidence | None = None
    reason: str | None = None


@dataclass(frozen=True)
class BlueprintChangePreview:
    """PURPOSE read-only preview of a Blueprint Engine change request
    DOMAIN  approved blueprint changes
    """

    allowed: bool
    operation_count: int = 0
    affected_files: tuple[Path, ...] = ()
    messages: tuple[str, ...] = ()
    blocked_reason: str | None = None


@dataclass
class BlueprintChangeResult:
    """PURPOSE result returned by Blueprint Engine apply methods
    DOMAIN  approved blueprint changes
    """

    success: bool = False
    patch_result: AuthorityPatchResult | None = None
    messages: list[str] = field(default_factory=list)
    blocked_reason: str | None = None
