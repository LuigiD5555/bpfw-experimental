"""Models used by the BPFW diff decision manager."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from bpfw.reports.finding import Finding


class DiffItemKind(Enum):
    """Stable diff item kinds shown by the diff manager."""

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
    """Risk labels used by the review screens."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class DiffActionLevel(Enum):
    """Classify how a diff item must be handled."""

    READ_ONLY = "READ_ONLY"
    SAFE_MECHANICAL_UPDATE = "SAFE_MECHANICAL_UPDATE"
    HUMAN_DECISION = "HUMAN_DECISION"


class SourceChangeKind(Enum):
    """Source-code actions that are outside BlueprintEngine authority writes."""

    DELETE_CODE_SYMBOL = "DELETE_CODE_SYMBOL"
    MARK_FOR_SOURCE_DELETE = "MARK_FOR_SOURCE_DELETE"


@dataclass(frozen=True)
class CodeTarget:
    """Represent a code symbol involved in a diff item.

    Attributes:
        path: Project-relative source file path.
        symbol: Symbol name detected in the source file.
        kind: Symbol kind such as class, function, or method.
        start_line: Optional starting line for the symbol.
        end_line: Optional ending line for the symbol.
        qualified_name: Optional fully qualified detected name.
    """

    path: str
    symbol: str
    kind: str
    start_line: int | None = None
    end_line: int | None = None
    qualified_name: str | None = None

    def display_label(self) -> str:
        """Return a compact source label.

        Returns:
            Human-readable code location.
        """
        return f"{self.path}::{self.symbol}"


@dataclass(frozen=True)
class BlueprintTarget:
    """Represent a blueprint block involved in a diff item.

    Attributes:
        block_id: Authority block identifier.
        path: Declared source path.
        symbol: Declared symbol.
        kind: Declared symbol kind.
        source_shard_path: Shard containing this block.
        purpose: Declared purpose.
        name: Declared display name.
        domain: Declared domain.
        status: Declared status or lifecycle value.
        block_data: Raw block dictionary.
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
        """Return a compact authority label.

        Returns:
            Human-readable block label.
        """
        if self.path and self.symbol:
            return f"{self.block_id} ({self.path}::{self.symbol})"
        return self.block_id


@dataclass(frozen=True)
class DiffItem:
    """One difference between real code and blueprint authority.

    Attributes:
        identifier: Stable identifier for the item within one diff session.
        kind: Category of difference.
        risk: Review risk label.
        reason: Human-readable explanation.
        finding: Original verification finding when the item came from verify.
        code_target: Code-side target, when applicable.
        blueprint_target: Authority-side target, when applicable.
        candidates: Candidate code targets for moved-code or replacement decisions.
        related_blocks: Extra authority blocks related to duplicate or conflict decisions.
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
    """Represent a source-code action planned by diff.

    Attributes:
        kind: Source-code action kind.
        target: Source code target.
        reason: Human-readable reason.
        apply_enabled: Whether automatic source edits are enabled.
    """

    kind: SourceChangeKind
    target: CodeTarget
    reason: str
    apply_enabled: bool = False
