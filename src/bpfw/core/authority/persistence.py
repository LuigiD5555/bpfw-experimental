"""PURPOSE low-level authority document persistence for BPFW
DOMAIN  blueprint files
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
    """PURPOSE result of a low-level authority document save operation
    DOMAIN  blueprint files
    """

    saved_shards: list[Path] = field(default_factory=list)
    created_shards: list[Path] = field(default_factory=list)
    removed_shards: list[Path] = field(default_factory=list)
    updated_includes: bool = False
    warnings: list[str] = field(default_factory=list)


class AuthorityPersistenceEngine:
    """PURPOSE save authority documents without layout synchronization
    DOMAIN  blueprint files
    """

    def __init__(self, project_root: Path) -> None:
        """PURPOSE set up the persistence engine
        DOMAIN  blueprint files
        """
        self.project_root = project_root

    def save_document(self, document: AuthorityDocument) -> AuthorityPersistenceResult:
        """PURPOSE save the document's shards and root index
        DOMAIN  blueprint files
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
        """PURPOSE save one block into its shard or the configured default shard
        DOMAIN  blueprint files
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
        """PURPOSE rebuild loaded shard contents using origins only
        DOMAIN  blueprint files
        """
        authority_config = document.get_authority_config()
        decision_engine = ShardDecisionEngine(authority_config)
        default_shard = decision_engine.get_default_shard()
        grouped_blocks: dict[Path, list[dict[str, Any]]] = {
            shard_path: [] for shard_path in document.shards
        }

        for block in blocks:
            block_id = block.get("id")
            if not isinstance(block_id, str) or not block_id.strip():
                result.warnings.append("Block missing id, skipping")
                continue

            origin = document.get_origin(block_id)
            if origin is None:
                origin = decision_engine.decide_shard_for_block(block, document)
                if not isinstance(origin, Path):
                    origin = default_shard
                document.block_origins[block_id] = origin
                if origin not in document.get_included_shard_paths():
                    document.index.add_include(origin)
                    result.updated_includes = True

            grouped_blocks.setdefault(origin, []).append(block)

        for shard_path, shard_blocks in grouped_blocks.items():
            if shard_path not in document.shards:
                document.shards[shard_path] = AuthorityShard(path=shard_path, blocks=[])
            document.shards[shard_path].set_blocks(shard_blocks)

    def _collect_blocks_from_shards(self, document: AuthorityDocument) -> list[dict[str, Any]]:
        """PURPOSE collect blocks from all loaded shards
        DOMAIN  blueprint files
        """
        blocks: list[dict[str, Any]] = []
        for shard in document.shards.values():
            blocks.extend(shard.get_blocks())
        return blocks

    def _synchronize_index_with_document(self, document: AuthorityDocument) -> None:
        """PURPOSE copy root metadata and includes from the document into the index
        DOMAIN  blueprint files
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
