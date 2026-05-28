"""PURPOSE models used by the BPFW diff decision manager
DOMAIN  optional integrations
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from bpfw.reports.finding import Finding


class DiffItemKind(Enum):
    """PURPOSE stable diff item kinds shown by the diff manager
    DOMAIN  optional integrations
    """

    UNDECLARED_CODE = "UNDECLARED_CODE"
    MISSING_DECLARED_CODE = "MISSING_DECLARED_CODE"
    MOVED_CODE_CANDIDATE = "MOVED_CODE_CANDIDATE"
    DUPLICATE_ACTIVE_PURPOSE = "DUPLICATE_ACTIVE_PURPOSE"
    INCOMPLETE_METADATA = "INCOMPLETE_METADATA"
    METADATA_DRIFT = "METADATA_DRIFT"
    INVALID_AUTHORITY = "INVALID_AUTHORITY"
    IGNORED_CODE_CONFLICT = "IGNORED_CODE_CONFLICT"
    ORPHAN_SHARD = "ORPHAN_SHARD"
    BROKEN_SHARD_REFERENCE = "BROKEN_SHARD_REFERENCE"


class DiffRisk(Enum):
    """PURPOSE risk labels used by the review screens
    DOMAIN  optional integrations
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class DiffActionLevel(Enum):
    """PURPOSE classify how a diff item must be handled
    DOMAIN  optional integrations
    """

    READ_ONLY = "READ_ONLY"
    SAFE_MECHANICAL_UPDATE = "SAFE_MECHANICAL_UPDATE"
    HUMAN_DECISION = "HUMAN_DECISION"


class SourceChangeKind(Enum):
    """PURPOSE source-code actions that are outside BlueprintEngine authority writes
    DOMAIN  optional integrations
    """

    DELETE_CODE_SYMBOL = "DELETE_CODE_SYMBOL"
    MARK_FOR_SOURCE_DELETE = "MARK_FOR_SOURCE_DELETE"


@dataclass(frozen=True)
class CodeTarget:
    """PURPOSE store information about a code symbol involved in a diff item
    DOMAIN  optional integrations
    """

    path: str
    symbol: str
    kind: str
    start_line: int | None = None
    end_line: int | None = None
    qualified_name: str | None = None

    def display_label(self) -> str:
        """PURPOSE get a compact source label
        DOMAIN  optional integrations
        """
        return f"{self.path}::{self.symbol}"


@dataclass(frozen=True)
class BlueprintTarget:
    """PURPOSE store information about a blueprint block involved in a diff item
    DOMAIN  optional integrations
    """

    block_id: str
    path: str | None = None
    symbol: str | None = None
    kind: str | None = None
    source_shard_path: Path | None = None
    purpose: str | None = None
    name: str | None = None
    domain: str | None = None
    status: str | None = None
    block_data: dict[str, Any] = field(default_factory=dict)

    def display_label(self) -> str:
        """PURPOSE get a compact authority label
        DOMAIN  optional integrations
        """
        if self.path and self.symbol:
            return f"{self.block_id} ({self.path}::{self.symbol})"
        return self.block_id


@dataclass(frozen=True)
class DiffItem:
    """PURPOSE one difference between real code and blueprint authority
    DOMAIN  optional integrations
    """

    identifier: str
    kind: DiffItemKind
    action_level: DiffActionLevel
    risk: DiffRisk
    reason: str
    finding: Finding | None = None
    code_target: CodeTarget | None = None
    blueprint_target: BlueprintTarget | None = None
    candidates: tuple[CodeTarget, ...] = ()
    related_blocks: tuple[BlueprintTarget, ...] = ()


@dataclass(frozen=True)
class SourceChangeRequest:
    """PURPOSE store information about a source-code action planned by diff
    DOMAIN  optional integrations
    """

    kind: SourceChangeKind
    target: CodeTarget
    reason: str
    apply_enabled: bool = False
