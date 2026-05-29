"""Low-level authority document persistence for BPFW.

This module persists the in-memory authority document and synchronizes shard
layout mechanically based on the configured shard strategy.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bpfw.core.authority.document import AuthorityDocument
from bpfw.core.authority.shard import AuthorityShard
from bpfw.core.authority.sharding import ShardDecisionEngine
from bpfw.core.catalog.access_control import (
    ensure_blueprint_can_be_written,
    has_temporary_blueprint_unlock_authorization,
)
from bpfw.core.errors import BlueprintLockedError
from bpfw.core.protection.authority import (
    get_authority_protection_status,
    lock_authority,
    unlock_authority,
)


@dataclass
class AuthorityPersistenceResult:
    """Result of a low-level authority document save operation.

    Attributes:
        saved_shards: Shard files written to disk.
        created_shards: Shard files created during save.
        removed_shards: Shard files removed during save.
        updated_includes: Whether root includes were written.
        warnings: Non-fatal persistence messages.
    """

    saved_shards: list[Path] = field(default_factory=list)
    created_shards: list[Path] = field(default_factory=list)
    removed_shards: list[Path] = field(default_factory=list)
    updated_includes: bool = False
    warnings: list[str] = field(default_factory=list)


class AuthorityPersistenceEngine:
    """Save authority documents with mechanical shard layout synchronization."""

    def __init__(self, project_root: Path) -> None:
        """Initialize the persistence engine.

        Args:
            project_root: Project root directory.
        """
        self.project_root = project_root

    def save_document(self, document: AuthorityDocument) -> AuthorityPersistenceResult:
        """Persist the document's current shards and root index.

        Args:
            document: Authority document to save exactly as currently modeled.

        Returns:
            Persistence result describing files written.
        """
        result = AuthorityPersistenceResult()
        lock_state = get_authority_protection_status(project_root=self.project_root).status
        requires_temporary_unlock = lock_state in {"locked", "degraded"}
        temporarily_unlocked = False

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
            blocks = document.get_blocks()
            if not blocks:
                result.warnings.append("No blocks to save")

            self._rebuild_current_shards_from_document(document=document, blocks=blocks, result=result)

            for shard_path, shard in document.shards.items():
                if not (self.project_root / shard_path).exists():
                    result.created_shards.append(shard_path)
                shard.sort_blocks()
                shard.save(self.project_root)
                result.saved_shards.append(shard_path)

            self._synchronize_index_with_document(document=document)
            document.index.save(self.project_root)
            result.updated_includes = True
            return result
        finally:
            if temporarily_unlocked:
                relock_result = lock_authority(project_root=self.project_root)
                if relock_result.status not in {"locked", "degraded"}:
                    raise BlueprintLockedError(
                        "Blueprint was written, but automatic re-lock failed. "
                        f"Current lock status: {relock_result.status}."
                    )

    def save_block(
        self,
        document: AuthorityDocument,
        block: dict[str, Any],
    ) -> AuthorityPersistenceResult:
        """Save one block into its current shard or the configured default shard.

        This method does not move an existing block to an expected shard. New
        blocks are placed in the default shard unless the caller already inserted
        them into a specific shard in the document.

        Args:
            document: Authority document to update.
            block: Block dictionary to save.

        Returns:
            Persistence result describing files written.
        """
        block_id = block.get("id")
        if not isinstance(block_id, str) or not block_id.strip():
            result = AuthorityPersistenceResult()
            result.warnings.append("Block missing id")
            return result

        origin = document.get_origin(block_id)
        if origin is None:
            authority_config = document.get_authority_config()
            decision_engine = ShardDecisionEngine(authority_config)
            origin = decision_engine.get_default_shard()
            if origin not in document.shards:
                document.shards[origin] = AuthorityShard(path=origin, blocks=[])
                document.index.add_include(origin)
            document.block_origins[block_id] = origin

        shard = document.shards.get(origin)
        if shard is None:
            shard = AuthorityShard(path=origin, blocks=[])
            document.shards[origin] = shard
            document.index.add_include(origin)

        blocks = shard.get_blocks()
        replaced = False
        for index, existing_block in enumerate(blocks):
            if isinstance(existing_block, dict) and existing_block.get("id") == block_id:
                blocks[index] = block
                replaced = True
                break
        if not replaced:
            blocks.append(block)

        shard.set_blocks(blocks)
        document.replace_blocks(self._collect_blocks_from_shards(document))
        return self.save_document(document)

    def _rebuild_current_shards_from_document(
        self,
        document: AuthorityDocument,
        blocks: list[dict[str, Any]],
        result: AuthorityPersistenceResult,
    ) -> None:
        """Rebuild shard contents from current block metadata and strategy.

        Args:
            document: Authority document to update.
            blocks: Logical block list from the document.
            result: Persistence result to record warnings and created shards.
        """
        authority_config = document.get_authority_config()
        decision_engine = ShardDecisionEngine(authority_config)
        default_shard = decision_engine.get_default_shard()
        grouped_blocks: dict[Path, list[dict[str, Any]]] = {}
        current_block_ids: set[str] = set()

        for block in blocks:
            block_id = block.get("id")
            if not isinstance(block_id, str) or not block_id.strip():
                result.warnings.append("Block missing id, skipping")
                continue
            current_block_ids.add(block_id)

            expected_shard = decision_engine.decide_shard_for_block(block, document)
            if not isinstance(expected_shard, Path):
                expected_shard = default_shard
            document.block_origins[block_id] = expected_shard
            if expected_shard not in document.get_included_shard_paths():
                document.index.add_include(expected_shard)
                result.updated_includes = True

            grouped_blocks.setdefault(expected_shard, []).append(block)

        stale_block_ids = [block_id for block_id in document.block_origins if block_id not in current_block_ids]
        for block_id in stale_block_ids:
            document.block_origins.pop(block_id, None)

        removed_shard_paths: list[Path] = []
        for shard_path in list(document.shards.keys()):
            if shard_path in grouped_blocks:
                continue
            absolute_path = self.project_root / shard_path
            if absolute_path.exists():
                try:
                    absolute_path.unlink()
                    removed_shard_paths.append(shard_path)
                except OSError as error:
                    result.warnings.append(f"Failed to delete shard '{shard_path}': {error}")
            document.shards.pop(shard_path, None)
            document.index.remove_include(shard_path)
            result.updated_includes = True

        if not grouped_blocks:
            grouped_blocks[default_shard] = []
            if default_shard not in document.get_included_shard_paths():
                document.index.add_include(default_shard)
                result.updated_includes = True

        for shard_path, shard_blocks in grouped_blocks.items():
            if shard_path not in document.shards:
                document.shards[shard_path] = AuthorityShard(path=shard_path, blocks=[])
            document.shards[shard_path].set_blocks(shard_blocks)

        result.removed_shards.extend(removed_shard_paths)

    def _collect_blocks_from_shards(self, document: AuthorityDocument) -> list[dict[str, Any]]:
        """Collect blocks from all loaded shards.

        Args:
            document: Authority document.

        Returns:
            Combined block list from all shards.
        """
        blocks: list[dict[str, Any]] = []
        for shard in document.shards.values():
            blocks.extend(shard.get_blocks())
        return blocks

    def _synchronize_index_with_document(self, document: AuthorityDocument) -> None:
        """Copy root metadata and includes from the document into the index.

        Args:
            document: Authority document whose root metadata should be saved.
        """
        blueprint_data = document.blueprint_data
        for key, value in blueprint_data.items():
            if key in {"blocks", "includes"}:
                continue
            document.index.data[key] = value

        document.index.data["includes"] = [
            str(shard_path)
            for shard_path in document.get_included_shard_paths()
        ]
        document.index.data.pop("blocks", None)
