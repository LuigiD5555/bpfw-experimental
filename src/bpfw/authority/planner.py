"""Authority reshard planner for BPFW."""

from dataclasses import dataclass, field
from pathlib import Path

from bpfw.authority.document import AuthorityDocument
from bpfw.authority.reshard.models import BlockMove
from bpfw.authority.sharding import ShardDecisionEngine


@dataclass
class ReshardPlan:
    """Plan for resharding blocks based on current strategy."""
    
    strategy: str
    default_shard: Path
    moves: list[BlockMove] = field(default_factory=list)
    shards_to_create: list[Path] = field(default_factory=list)
    shards_to_remove: list[Path] = field(default_factory=list)
    includes_to_add: list[Path] = field(default_factory=list)
    includes_to_remove: list[Path] = field(default_factory=list)
    duplicate_block_ids: list[tuple[str, Path, Path]] = field(default_factory=list)
    duplicate_code_declarations: list[tuple[str, Path, str, Path]] = field(default_factory=list)
    
    def has_changes(self) -> bool:
        """Check if the plan has any changes to apply.
        
        Returns:
            True if there are changes, False otherwise.
        """
        return (
            bool(self.moves) or
            bool(self.shards_to_create) or
            bool(self.shards_to_remove) or
            bool(self.includes_to_add) or
            bool(self.includes_to_remove) or
            bool(self.duplicate_block_ids) or
            bool(self.duplicate_code_declarations)
        )
    
    def move_count(self) -> int:
        """Get the number of block moves in the plan.
        
        Returns:
            Number of moves.
        """
        return len(self.moves)


class AuthorityReshardPlanner:
    """Plan and apply shard reorganization operations.
    
    This planner:
    - Computes which blocks need to move based on shard strategy
    - Identifies shards to create or remove
    - Detects duplicate block IDs and code declarations
    - Applies the plan when requested
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize the reshard planner.
        
        Args:
            project_root: The project root directory.
        """
        self.project_root = project_root

    def build_plan(self, document: AuthorityDocument) -> ReshardPlan:
        """Build a reshard plan for the given document.
        
        Args:
            document: The authority document to analyze.
        
        Returns:
            ReshardPlan describing the needed changes.
        """
        # Get authority config
        authority_config = document.get_authority_config()
        decision_engine = ShardDecisionEngine(authority_config)
        
        strategy = decision_engine.shard_strategy
        default_shard = decision_engine.get_default_shard()
        
        plan = ReshardPlan(
            strategy=strategy,
            default_shard=default_shard,
        )
        
        # Track expected shards
        expected_shards: set[Path] = set()
        
        # Track block IDs for duplicate detection
        seen_block_ids: dict[str, list[tuple[str, Path]]] = {}
        
        # Track code declarations for duplicate detection
        seen_code_declarations: dict[str, list[tuple[str, Path]]] = {}
        
        # Analyze each block
        for block in document.get_blocks():
            block_id = block.get("id")
            if not block_id:
                continue
            
            # Get current shard
            current_shard = document.get_origin(block_id)
            if current_shard is None:
                # New block, assign to default
                current_shard = default_shard
            
            # Determine expected shard
            expected_shard = decision_engine.decide_shard_for_block(block, document)
            expected_shards.add(expected_shard)
            
            # Check for move
            if current_shard != expected_shard:
                reason = self._determine_move_reason(block, current_shard, expected_shard, decision_engine)
                plan.moves.append(BlockMove(
                    block_id=block_id,
                    from_shard=current_shard,
                    to_shard=expected_shard,
                    reason=reason,
                ))
            
            # Track for duplicate detection
            if block_id in seen_block_ids:
                seen_block_ids[block_id].append((block_id, current_shard))
            else:
                seen_block_ids[block_id] = [(block_id, current_shard)]
            
            # Track code declaration
            code = block.get("code")
            if isinstance(code, dict):
                code_path = code.get("path", "")
                symbol = code.get("symbol", "")
                kind = code.get("kind", "")
                
                if code_path and symbol and kind:
                    # Create unique key for code declaration
                    code_key = f"{code_path}:{symbol}:{kind}"
                    
                    if code_key in seen_code_declarations:
                        seen_code_declarations[code_key].append((block_id, current_shard))
                    else:
                        seen_code_declarations[code_key] = [(block_id, current_shard)]
        
        # Identify duplicate block IDs
        for block_id, locations in seen_block_ids.items():
            if len(locations) > 1:
                # Report all pairs
                for i in range(len(locations)):
                    for j in range(i + 1, len(locations)):
                        _, shard_a = locations[i]
                        _, shard_b = locations[j]
                        plan.duplicate_block_ids.append((block_id, shard_a, shard_b))
        
        # Identify duplicate code declarations
        for code_key, locations in seen_code_declarations.items():
            if len(locations) > 1:
                # Report all pairs
                for i in range(len(locations)):
                    for j in range(i + 1, len(locations)):
                        block_id_a, shard_a = locations[i]
                        block_id_b, shard_b = locations[j]
                        plan.duplicate_code_declarations.append((block_id_a, shard_a, block_id_b, shard_b))
        
        # Identify shards to create
        current_shards = set(document.get_shard_paths())
        plan.shards_to_create = list(expected_shards - current_shards)
        
        # Identify shards to remove (empty shards not in expected set)
        for shard_path in current_shards:
            if shard_path not in expected_shards:
                shard = document.shards.get(shard_path)
                if shard and shard.is_empty():
                    plan.shards_to_remove.append(shard_path)
        
        # Identify includes to add
        current_includes = set(document.get_included_shard_paths())
        plan.includes_to_add = list(expected_shards - current_includes)
        
        # Identify includes to remove (removed empty shards)
        plan.includes_to_remove = plan.shards_to_remove.copy()
        
        return plan

    def apply_plan(self, document: AuthorityDocument, plan: ReshardPlan) -> None:
        """Apply a reshard plan to the document.
        
        This updates the document's block_origins and shards in place.
        To persist changes, use AuthorityPersistenceEngine.save_document().
        
        Args:
            document: The authority document to update.
            plan: The reshard plan to apply.
        """
        # Update block origins for moves
        for move in plan.moves:
            document.block_origins[move.block_id] = move.to_shard
        
        # Remove blocks from old shards
        for move in plan.moves:
            old_shard = document.shards.get(move.from_shard)
            if old_shard:
                old_shard.remove_block(move.block_id)
        
        # Add blocks to new shards (they will be re-assigned during save)
        # This is handled by the persistence engine during save_document()
        
        # Remove empty shards
        for shard_path in plan.shards_to_remove:
            if shard_path in document.shards:
                del document.shards[shard_path]
            document.index.remove_include(shard_path)
        
        # Add new shard includes
        for shard_path in plan.includes_to_add:
            document.index.add_include(shard_path)
        
        # Remove shard includes
        for shard_path in plan.includes_to_remove:
            document.index.remove_include(shard_path)

    def _determine_move_reason(
        self,
        block: dict,
        current_shard: Path,
        expected_shard: Path,
        decision_engine: ShardDecisionEngine,
    ) -> str:
        """Determine the reason for a block move.
        
        Args:
            block: The block dictionary.
            current_shard: Current shard path.
            expected_shard: Expected shard path.
            decision_engine: The shard decision engine.
        
        Returns:
            Reason string for the move.
        """
        strategy = decision_engine.shard_strategy

        if strategy == "domain":
            domain = block.get("domain", "")
            if domain:
                return "domain_changed"
            else:
                return "default_shard"

        elif strategy == "path":
            code = block.get("code", {})
            if isinstance(code, dict):
                code_path = code.get("path", "")
                if code_path:
                    return "path_changed"
            return "default_shard"

        elif strategy == "architecture_layer":
            code = block.get("code", {})
            if isinstance(code, dict):
                code_path = code.get("path", "")
                if code_path:
                    return "architecture_layer_changed"
            return "default_shard"

        else:
            return "shard_strategy_changed"
