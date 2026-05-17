"""Authority persistence engine for BPFW sharded blueprint."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bpfw.authority.document import AuthorityDocument
from bpfw.authority.reshard import ReshardCoordinator
from bpfw.authority.reshard.models import BlockMove
from bpfw.authority.sharding import ShardDecisionEngine
from bpfw.authority.shard import AuthorityShard
from bpfw.catalog.access_control import (
    ensure_blueprint_can_be_written,
    has_temporary_blueprint_unlock_authorization,
)
from bpfw.core.errors import BlueprintLockedError
from bpfw.protection.authority import (
    get_authority_protection_status,
    lock_authority,
    unlock_authority,
)


@dataclass
class AuthorityPersistenceResult:
    """Result of a document save operation."""
    
    saved_shards: list[Path] = field(default_factory=list)
    created_shards: list[Path] = field(default_factory=list)
    removed_shards: list[Path] = field(default_factory=list)
    moved_blocks: list[BlockMove] = field(default_factory=list)
    updated_includes: bool = False
    warnings: list[str] = field(default_factory=list)


class AuthorityPersistenceEngine:
    """Handle physical persistence of authority documents to shards.
    
    This engine:
    - Determines where blocks should live based on shard strategy
    - Moves blocks between shards when necessary
    - Creates new shards when needed
    - Removes empty shards when configured
    - Updates includes in the index
    - Keeps physical layout synchronized with logical authority
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize the persistence engine.
        
        Args:
            project_root: The project root directory.
        """
        self.project_root = project_root
        self._reshard_coordinator = ReshardCoordinator(project_root=project_root)

    def save_document(self, document: AuthorityDocument) -> AuthorityPersistenceResult:
        """Save a document, moving blocks to correct shards as needed.
        
        Args:
            document: The authority document to save.
        
        Returns:
            AuthorityPersistenceResult describing what changed.
        """
        result = AuthorityPersistenceResult()
        lock_state = get_authority_protection_status(project_root=self.project_root).status
        requires_temporary_unlock = lock_state in {"locked", "degraded"}
        temporarily_unlocked = False

        if requires_temporary_unlock and not has_temporary_blueprint_unlock_authorization():
            ensure_blueprint_can_be_written(project_root=self.project_root)

        if requires_temporary_unlock and has_temporary_blueprint_unlock_authorization():
            unlock_result = unlock_authority(project_root=self.project_root)
            if unlock_result.status != "unlocked":
                raise BlueprintLockedError(
                    "Blueprint is locked and temporary unlock failed. "
                    "Run in an interactive terminal and approve temporary unlock."
                )
            temporarily_unlocked = True

        try:
            # Get authority config
            authority_config = document.get_authority_config()
            decision_engine = ShardDecisionEngine(authority_config)

            # Get configuration
            auto_create_shards = authority_config.get("auto_create_shards", True)
            remove_empty_shards = authority_config.get("remove_empty_shards", False)

            # Get all blocks
            blocks = document.get_blocks()
            if not blocks:
                # No blocks, just save empty default shard if needed
                result.warnings.append("No blocks to save")
                return result

            # Build plan from internal reshard coordinator.
            reshard_plan = self._reshard_coordinator.build_sync_plan(document=document)

            # Group blocks by expected shard
            shard_blocks: dict[Path, list[dict[str, Any]]] = {}

            for block in blocks:
                block_id = block.get("id")
                if not block_id:
                    result.warnings.append("Block missing id, skipping")
                    continue

                # Determine expected shard
                expected_shard = decision_engine.decide_shard_for_block(block, document)

                # Get current shard
                current_shard = document.get_origin(block_id)

                if current_shard is None:
                    # New block, just assign to expected shard
                    current_shard = expected_shard

                # Add to expected shard group
                shard_blocks.setdefault(expected_shard, []).append(block)

            # Apply moves to block_origins
            for move in reshard_plan.moves:
                document.block_origins[move.block_id] = move.to_shard
                result.moved_blocks.append(move)

            # Collect all shards that need to be written
            shards_to_write = set()

            # Add all expected shards with blocks
            for shard_path in shard_blocks.keys():
                shards_to_write.add(shard_path)

            # Add all old shards that had blocks moved away
            for move in result.moved_blocks:
                shards_to_write.add(move.from_shard)

            # Create or update shards
            for shard_path in shards_to_write:
                # Check if shard exists
                if shard_path in document.shards:
                    # Update existing shard
                    shard = document.shards[shard_path]
                    shard.set_blocks(shard_blocks.get(shard_path, []))
                else:
                    # Create new shard
                    if not auto_create_shards:
                        result.warnings.append(
                            f"Would create shard {shard_path} but auto_create_shards is false"
                        )
                        continue

                    shard = AuthorityShard(path=shard_path, blocks=shard_blocks.get(shard_path, []))
                    document.shards[shard_path] = shard
                    result.created_shards.append(shard_path)

                # Sort blocks for deterministic output
                shard.sort_blocks()

                # Save shard
                shard.save(self.project_root)
                result.saved_shards.append(shard_path)

            # Handle empty shards
            if remove_empty_shards:
                shards_to_remove = []
                for shard_path, shard in document.shards.items():
                    if shard.is_empty() and shard_path not in shards_to_write:
                        # Shard is empty and not being written, remove it
                        shards_to_remove.append(shard_path)

                for shard_path in shards_to_remove:
                    # Remove file
                    absolute_path = self.project_root / shard_path
                    if absolute_path.exists():
                        absolute_path.unlink()

                    # Remove from document
                    del document.shards[shard_path]
                    result.removed_shards.append(shard_path)

                    # Remove from includes
                    document.index.remove_include(shard_path)
                    result.updated_includes = True

            # Update includes if new shards were created
            if result.created_shards:
                for shard_path in result.created_shards:
                    if shard_path not in document.get_included_shard_paths():
                        document.index.add_include(shard_path)
                        result.updated_includes = True

            # Save index if includes changed
            if result.updated_includes:
                document.index.save(self.project_root)
            return result
        finally:
            if temporarily_unlocked:
                relock_result = lock_authority(project_root=self.project_root)
                if relock_result.status not in {"locked", "degraded"}:
                    raise BlueprintLockedError(
                        "Blueprint was written, but automatic re-lock failed. "
                        f"Current lock status: {relock_result.status}."
                    )

    def save_block(self, document: AuthorityDocument, block: dict[str, Any]) -> AuthorityPersistenceResult:
        """Save a single block, moving it if needed.
        
        Args:
            document: The authority document.
            block: The block dictionary to save.
        
        Returns:
            AuthorityPersistenceResult describing what changed.
        """
        block_id = block.get("id")
        if not block_id:
            result = AuthorityPersistenceResult()
            result.warnings.append("Block missing id")
            return result

        # Get all blocks
        blocks = document.get_blocks()

        # Find and replace the block
        found = False
        for i, existing_block in enumerate(blocks):
            if isinstance(existing_block, dict) and existing_block.get("id") == block_id:
                blocks[i] = block
                found = True
                break

        if not found:
            blocks.append(block)

        # Update document
        document.replace_blocks(blocks)

        # Save
        return self.save_document(document)

    def move_block_if_needed(
        self,
        document: AuthorityDocument,
        block: dict[str, Any],
    ) -> BlockMove | None:
        """Check if a block needs to be moved and return the move if so.
        
        This does not apply the move, it only determines if a move is needed.
        
        Args:
            document: The authority document.
            block: The block dictionary to check.
        
        Returns:
            BlockMove if a move is needed, None otherwise.
        """
        block_id = block.get("id")
        if not block_id:
            return None

        # Get authority config
        authority_config = document.get_authority_config()
        decision_engine = ShardDecisionEngine(authority_config)

        # Determine expected shard
        expected_shard = decision_engine.decide_shard_for_block(block, document)

        # Get current shard
        current_shard = document.get_origin(block_id)

        if current_shard is None or current_shard == expected_shard:
            return None

        # Move is needed
        reason = self._determine_move_reason(block, current_shard, expected_shard, decision_engine)

        return BlockMove(
            block_id=block_id,
            from_shard=current_shard,
            to_shard=expected_shard,
            reason=reason,
        )

    def _determine_move_reason(
        self,
        block: dict[str, Any],
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
