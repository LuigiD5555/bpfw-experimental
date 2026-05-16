"""Reshard coordination for automatic authority synchronization."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bpfw.authority.document import AuthorityDocument
from bpfw.authority.reshard.models import BlockMove
from bpfw.authority.sharding import ShardDecisionEngine


class ReshardMode:
    """Stable labels for reshard operation size."""

    NO_DRIFT = "no_drift"
    SMALL = "small"
    MEDIUM = "medium"
    MIGRATION = "migration"


@dataclass
class ReshardSyncPlan:
    """Computed synchronization plan for current authority state."""

    strategy: str
    moves: list[BlockMove] = field(default_factory=list)
    expected_shards: set[Path] = field(default_factory=set)
    mode: str = ReshardMode.NO_DRIFT

    def move_count(self) -> int:
        return len(self.moves)

    def affected_shard_count(self) -> int:
        shard_paths: set[Path] = set()
        for move in self.moves:
            shard_paths.add(move.from_shard)
            shard_paths.add(move.to_shard)
        return len(shard_paths)

    def requires_confirmation(self) -> bool:
        return self.mode == ReshardMode.MIGRATION


class ReshardCoordinator:
    """Build and classify internal reshard synchronization operations."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def build_sync_plan(self, document: AuthorityDocument) -> ReshardSyncPlan:
        authority_config = document.get_authority_config()
        decision_engine = ShardDecisionEngine(authority_config)

        plan = ReshardSyncPlan(strategy=decision_engine.shard_strategy)

        for block in document.get_blocks():
            block_id = block.get("id")
            if not block_id:
                continue

            expected_shard = decision_engine.decide_shard_for_block(block, document)
            plan.expected_shards.add(expected_shard)

            current_shard = document.get_origin(block_id)
            if current_shard is None:
                continue
            if current_shard == expected_shard:
                continue

            plan.moves.append(
                BlockMove(
                    block_id=block_id,
                    from_shard=current_shard,
                    to_shard=expected_shard,
                    reason=self._determine_move_reason(block, decision_engine),
                )
            )

        plan.mode = self._classify_plan(plan, authority_config)
        return plan

    def _classify_plan(self, plan: ReshardSyncPlan, authority_config: dict[str, Any]) -> str:
        move_count = plan.move_count()
        if move_count == 0:
            return ReshardMode.NO_DRIFT

        migration_threshold = int(authority_config.get("migration_confirmation_threshold", 500))
        medium_threshold = int(authority_config.get("medium_reshard_threshold", 10))

        if move_count >= migration_threshold:
            return ReshardMode.MIGRATION
        if move_count >= medium_threshold:
            return ReshardMode.MEDIUM
        return ReshardMode.SMALL

    def _determine_move_reason(self, block: dict[str, Any], decision_engine: ShardDecisionEngine) -> str:
        strategy = decision_engine.shard_strategy
        if strategy == "domain":
            return "domain_changed" if block.get("domain") else "default_shard"
        if strategy == "path":
            code = block.get("code", {})
            if isinstance(code, dict) and code.get("path"):
                return "path_changed"
            return "default_shard"
        if strategy == "architecture_layer":
            code = block.get("code", {})
            if isinstance(code, dict) and code.get("path"):
                return "architecture_layer_changed"
            return "default_shard"
        return "shard_strategy_changed"
