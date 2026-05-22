"""Blueprint authority layout planning.

This module computes mechanical shard placement changes. It does not apply the
changes and does not decide whether drift should be accepted.
"""

from dataclasses import dataclass, field
from pathlib import Path

from bpfw.authority.document import AuthorityDocument
from bpfw.authority.sharding import ShardDecisionEngine


@dataclass(frozen=True)
class BlockPlacementChange:
    """Represent one block placement change between shards.

    Attributes:
        block_id: Authority block identifier.
        source_shard: Current shard path.
        target_shard: Expected shard path.
        reason: Mechanical reason for the placement change.
    """

    block_id: str
    source_shard: Path
    target_shard: Path
    reason: str


@dataclass
class BlueprintLayoutPlan:
    """Plan describing mechanical shard layout changes.

    Attributes:
        strategy: Shard strategy used to compute placement.
        default_shard: Default shard path from authority config.
        moves: Block placement changes.
        shards_to_create: Expected shards that are not present.
        shards_to_remove: Empty shards that are no longer expected.
        includes_to_add: Includes that should be added to the root blueprint.
        includes_to_remove: Includes that should be removed from the root blueprint.
        duplicate_block_ids: Duplicate block ID findings.
        duplicate_code_declarations: Duplicate code declaration findings.
    """

    strategy: str
    default_shard: Path
    moves: list[BlockPlacementChange] = field(default_factory=list)
    shards_to_create: list[Path] = field(default_factory=list)
    shards_to_remove: list[Path] = field(default_factory=list)
    includes_to_add: list[Path] = field(default_factory=list)
    includes_to_remove: list[Path] = field(default_factory=list)
    duplicate_block_ids: list[tuple[str, Path, Path]] = field(default_factory=list)
    duplicate_code_declarations: list[tuple[str, Path, str, Path]] = field(default_factory=list)

    def has_changes(self) -> bool:
        """Return whether the layout plan contains any change or conflict.

        Returns:
            True when there are moves, include changes, shard changes, or duplicates.
        """
        return (
            bool(self.moves)
            or bool(self.shards_to_create)
            or bool(self.shards_to_remove)
            or bool(self.includes_to_add)
            or bool(self.includes_to_remove)
            or bool(self.duplicate_block_ids)
            or bool(self.duplicate_code_declarations)
        )

    def move_count(self) -> int:
        """Return the number of block placement moves.

        Returns:
            Number of planned block moves.
        """
        return len(self.moves)


class BlueprintLayoutPlanner:
    """Build read-only shard layout plans for authority documents."""

    def __init__(self, project_root: Path) -> None:
        """Initialize the planner.

        Args:
            project_root: Project root directory.
        """
        self.project_root = project_root

    def build_plan(self, document: AuthorityDocument) -> BlueprintLayoutPlan:
        """Build a read-only layout plan for an authority document.

        Args:
            document: Loaded authority document.

        Returns:
            Blueprint layout plan.
        """
        authority_config = document.get_authority_config()
        decision_engine = ShardDecisionEngine(authority_config)
        plan = BlueprintLayoutPlan(
            strategy=decision_engine.shard_strategy,
            default_shard=decision_engine.get_default_shard(),
        )

        expected_shards: set[Path] = set()
        seen_block_ids: dict[str, list[Path]] = {}
        seen_code_declarations: dict[str, list[tuple[str, Path]]] = {}

        for block in document.get_blocks():
            block_id = block.get("id")
            if not isinstance(block_id, str) or not block_id.strip():
                continue

            current_shard = document.get_origin(block_id) or plan.default_shard
            expected_shard = decision_engine.decide_shard_for_block(block, document)
            expected_shards.add(expected_shard)

            if current_shard != expected_shard:
                plan.moves.append(
                    BlockPlacementChange(
                        block_id=block_id,
                        source_shard=current_shard,
                        target_shard=expected_shard,
                        reason=self._determine_move_reason(block, decision_engine),
                    )
                )

            seen_block_ids.setdefault(block_id, []).append(current_shard)
            code_key = self._code_declaration_key(block)
            if code_key is not None:
                seen_code_declarations.setdefault(code_key, []).append((block_id, current_shard))

        self._collect_duplicate_block_ids(seen_block_ids, plan)
        self._collect_duplicate_code_declarations(seen_code_declarations, plan)
        self._collect_shard_changes(document, expected_shards, plan)
        return plan

    def _collect_duplicate_block_ids(
        self,
        seen_block_ids: dict[str, list[Path]],
        plan: BlueprintLayoutPlan,
    ) -> None:
        """Collect duplicate block ID conflicts into the plan.

        Args:
            seen_block_ids: Mapping of block IDs to shard locations.
            plan: Plan to mutate with duplicate findings.
        """
        for block_id, shard_paths in seen_block_ids.items():
            if len(shard_paths) <= 1:
                continue
            for left_index in range(len(shard_paths)):
                for right_index in range(left_index + 1, len(shard_paths)):
                    plan.duplicate_block_ids.append(
                        (block_id, shard_paths[left_index], shard_paths[right_index])
                    )

    def _collect_duplicate_code_declarations(
        self,
        seen_code_declarations: dict[str, list[tuple[str, Path]]],
        plan: BlueprintLayoutPlan,
    ) -> None:
        """Collect duplicate code declaration conflicts into the plan.

        Args:
            seen_code_declarations: Mapping of declaration keys to block locations.
            plan: Plan to mutate with duplicate findings.
        """
        for locations in seen_code_declarations.values():
            if len(locations) <= 1:
                continue
            for left_index in range(len(locations)):
                for right_index in range(left_index + 1, len(locations)):
                    left_block_id, left_shard = locations[left_index]
                    right_block_id, right_shard = locations[right_index]
                    plan.duplicate_code_declarations.append(
                        (left_block_id, left_shard, right_block_id, right_shard)
                    )

    def _collect_shard_changes(
        self,
        document: AuthorityDocument,
        expected_shards: set[Path],
        plan: BlueprintLayoutPlan,
    ) -> None:
        """Collect shard and include changes into the plan.

        Args:
            document: Loaded authority document.
            expected_shards: Expected shard paths from block placement.
            plan: Plan to mutate.
        """
        current_shards = set(document.get_shard_paths())
        current_includes = set(document.get_included_shard_paths())

        plan.shards_to_create = sorted(expected_shards - current_shards)
        plan.includes_to_add = sorted(expected_shards - current_includes)

        for shard_path in sorted(current_shards):
            if shard_path in expected_shards:
                continue
            shard = document.shards.get(shard_path)
            if shard is not None and shard.is_empty():
                plan.shards_to_remove.append(shard_path)
                if shard_path in current_includes:
                    plan.includes_to_remove.append(shard_path)

    def _determine_move_reason(
        self,
        block: dict,
        decision_engine: ShardDecisionEngine,
    ) -> str:
        """Determine a mechanical reason for a shard placement change.

        Args:
            block: Authority block dictionary.
            decision_engine: Shard decision engine used for placement.

        Returns:
            Reason label.
        """
        strategy = decision_engine.shard_strategy
        if strategy == "domain":
            return "domain_changed" if block.get("domain") else "default_shard"
        if strategy == "path":
            code = block.get("code", {})
            return "path_changed" if isinstance(code, dict) and code.get("path") else "default_shard"
        if strategy == "architecture_layer":
            code = block.get("code", {})
            return "architecture_layer_changed" if isinstance(code, dict) and code.get("path") else "default_shard"
        return "shard_strategy_changed"

    def _code_declaration_key(self, block: dict) -> str | None:
        """Build a stable code declaration key for one block.

        Args:
            block: Authority block dictionary.

        Returns:
            Stable key or None when code metadata is incomplete.
        """
        code = block.get("code")
        if not isinstance(code, dict):
            return None
        code_path = code.get("path")
        symbol = code.get("symbol")
        kind = code.get("kind")
        if not all(isinstance(value, str) and value.strip() for value in (code_path, symbol, kind)):
            return None
        return f"{code_path}:{symbol}:{kind}"
