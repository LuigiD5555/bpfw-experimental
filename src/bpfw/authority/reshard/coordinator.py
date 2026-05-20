"""Reshard coordination for automatic authority synchronization."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from bpfw.authority.document import AuthorityDocument
from bpfw.authority.errors import AuthorityError
from bpfw.authority.reshard.models import BlockMove
from bpfw.authority.sharding import ShardDecisionEngine
from bpfw.catalog.access_control import authorize_blueprint_writes_for_tool, ensure_blueprint_can_be_written
from bpfw.core.errors import BlueprintLockedError


class ReshardMode:
    """Stable labels for reshard operation size."""

    NO_DRIFT = "no_drift"
    SMALL = "small"
    MEDIUM = "medium"
    MIGRATION = "migration"


@dataclass(frozen=True)
class AuthoritySyncResult:
    """Summarize one automatic authority shard synchronization attempt.

    Attributes:
        mode: Size classification reported by the reshard coordinator.
        moved_blocks: Blocks moved between shards during synchronization.
        migrated_root_blocks: Legacy root-level blocks migrated into shard storage.
        skipped_root_blocks: Legacy root-level blocks skipped because they already existed.
        created_shards: Shards created during synchronization.
        removed_shards: Shards removed during synchronization.
        updated_includes: Whether the root index includes changed.
        skipped_reason: Reason synchronization was skipped, if no safe write was performed.
    """

    mode: str = ReshardMode.NO_DRIFT
    moved_blocks: tuple[BlockMove, ...] = ()
    migrated_root_blocks: int = 0
    skipped_root_blocks: int = 0
    created_shards: tuple[Path, ...] = ()
    removed_shards: tuple[Path, ...] = ()
    updated_includes: bool = False
    skipped_reason: str | None = None

    def has_changes(self) -> bool:
        """Return whether the synchronization attempt changed authority files.

        Returns:
            True when any shard, include, or root-level block migration changed.
        """

        return (
            bool(self.moved_blocks)
            or self.migrated_root_blocks > 0
            or bool(self.created_shards)
            or bool(self.removed_shards)
            or self.updated_includes
        )


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


def _declaration_key(block: dict[str, Any]) -> str | None:
    """Build a stable code declaration key for one authority block.

    Args:
        block: Authority block data read from the root blueprint or a shard.

    Returns:
        A stable declaration key, or None when required code metadata is missing.
    """

    code_data = block.get("code")
    if not isinstance(code_data, dict):
        return None
    code_path = code_data.get("path")
    code_symbol = code_data.get("symbol")
    code_kind = code_data.get("kind")
    if not all(isinstance(value, str) and value.strip() for value in (code_path, code_symbol, code_kind)):
        return None
    return f"{code_path}:{code_symbol}:{code_kind}"


def _load_raw_blueprint_data(project_root: Path) -> dict[str, Any] | None:
    """Load raw root blueprint data without enforcing the sharded index rules.

    Args:
        project_root: Root directory containing the BPFW authority files.

    Returns:
        Raw blueprint dictionary, or None when the blueprint is missing or not a dictionary.

    Raises:
        OSError: If the blueprint cannot be read.
        yaml.YAMLError: If the blueprint contains invalid YAML.
    """

    blueprint_path = project_root / "bpfw" / "blueprint.yaml"
    if not blueprint_path.exists():
        return None

    data = yaml.safe_load(blueprint_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    return data


def _is_sharded_authority(data: dict[str, Any] | None) -> bool:
    """Return whether raw blueprint data declares sharded authority layout.

    Args:
        data: Raw root blueprint data.

    Returns:
        True when the authority layout is sharded, otherwise False.
    """

    if data is None:
        return False
    authority = data.get("authority")
    return isinstance(authority, dict) and authority.get("layout") == "sharded"


def migrate_root_blocks_to_default_shard(project_root: Path) -> dict[str, int]:
    """Move legacy root-level blocks into the default shard when possible.

    Args:
        project_root: Root directory containing BPFW authority files.

    Returns:
        Summary counters for migrated, skipped, and total shard blocks.

    Raises:
        ImportError: If PyYAML is unavailable.
        OSError: If authority files cannot be read or written.
        BlueprintLockedError: If authority files are locked or write authorization is missing.
    """

    from bpfw.authority.shard import AuthorityShard

    blueprint_path = project_root / "bpfw" / "blueprint.yaml"
    data = _load_raw_blueprint_data(project_root=project_root)
    if not _is_sharded_authority(data):
        return {"migrated": 0, "skipped": 0, "shard_total": 0}

    authority = data.get("authority")
    if not isinstance(authority, dict):
        return {"migrated": 0, "skipped": 0, "shard_total": 0}

    root_blocks = data.get("blocks")
    if not isinstance(root_blocks, list) or not root_blocks:
        return {"migrated": 0, "skipped": 0, "shard_total": 0}

    includes = data.get("includes")
    include_values = includes if isinstance(includes, list) else []
    default_shard_value = authority.get("default_shard")
    if isinstance(default_shard_value, str) and default_shard_value.strip():
        default_shard_path = Path(default_shard_value)
    elif include_values:
        default_shard_path = Path(str(include_values[0]))
    else:
        default_shard_path = Path("bpfw/blocks/core.yaml")

    try:
        target_shard = AuthorityShard.load(project_root=project_root, shard_path=default_shard_path)
    except FileNotFoundError:
        target_shard = AuthorityShard(path=default_shard_path, blocks=[])

    shard_blocks = target_shard.get_blocks()
    existing_block_ids = {
        str(block_id)
        for block in shard_blocks
        if isinstance(block, dict)
        for block_id in [block.get("id")]
        if block_id
    }
    existing_declaration_keys = {
        declaration_key
        for block in shard_blocks
        if isinstance(block, dict)
        for declaration_key in [_declaration_key(block)]
        if declaration_key is not None
    }

    migrated_count = 0
    skipped_count = 0
    for root_block in root_blocks:
        if not isinstance(root_block, dict):
            skipped_count += 1
            continue
        root_block_id = root_block.get("id")
        if isinstance(root_block_id, str) and root_block_id in existing_block_ids:
            skipped_count += 1
            continue
        root_declaration_key = _declaration_key(root_block)
        if root_declaration_key is not None and root_declaration_key in existing_declaration_keys:
            skipped_count += 1
            continue
        shard_blocks.append(root_block)
        if isinstance(root_block_id, str):
            existing_block_ids.add(root_block_id)
        if root_declaration_key is not None:
            existing_declaration_keys.add(root_declaration_key)
        migrated_count += 1

    target_shard.set_blocks(shard_blocks)
    target_shard.sort_blocks()
    target_shard.save(project_root=project_root)

    if not isinstance(includes, list):
        data["includes"] = [str(default_shard_path)]
    elif str(default_shard_path) not in includes:
        includes.append(str(default_shard_path))

    data.pop("blocks", None)
    ensure_blueprint_can_be_written(project_root=project_root)
    blueprint_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return {"migrated": migrated_count, "skipped": skipped_count, "shard_total": len(shard_blocks)}


def synchronize_authority_shards(
    project_root: Path,
    allow_large_migration: bool = False,
) -> AuthoritySyncResult:
    """Synchronize sharded authority layout from the current canonical data.

    Args:
        project_root: Root directory containing BPFW authority files.
        allow_large_migration: Whether to apply migration-sized reshard plans.

    Returns:
        Synchronization result describing any applied changes or skipped reason.

    Raises:
        AuthorityError: If the sharded authority repository is invalid.
        BlueprintLockedError: If authority writes are not authorized or files are locked.
        ImportError: If required YAML support is unavailable.
        OSError: If authority files cannot be read or written.
        ValueError: If existing authority data is structurally invalid.
        yaml.YAMLError: If YAML parsing fails.
    """

    raw_blueprint_data = _load_raw_blueprint_data(project_root=project_root)
    if raw_blueprint_data is None:
        return AuthoritySyncResult(skipped_reason="missing_blueprint")
    if not _is_sharded_authority(raw_blueprint_data):
        return AuthoritySyncResult(skipped_reason="non_sharded_authority")

    from bpfw.authority.repository import AuthorityRepository

    migration_summary = migrate_root_blocks_to_default_shard(project_root=project_root)
    repository = AuthorityRepository(project_root=project_root)
    document = repository.load()
    coordinator = ReshardCoordinator(project_root=project_root)
    plan = coordinator.build_sync_plan(document=document)

    if plan.requires_confirmation() and not allow_large_migration:
        return AuthoritySyncResult(
            mode=plan.mode,
            migrated_root_blocks=migration_summary["migrated"],
            skipped_root_blocks=migration_summary["skipped"],
            skipped_reason="large_migration_requires_explicit_reshard",
        )

    if plan.mode == ReshardMode.NO_DRIFT and not migration_summary["migrated"] and not migration_summary["skipped"]:
        return AuthoritySyncResult(mode=plan.mode)

    persistence_result = repository.save(document)
    return AuthoritySyncResult(
        mode=plan.mode,
        moved_blocks=tuple(persistence_result.moved_blocks),
        migrated_root_blocks=migration_summary["migrated"],
        skipped_root_blocks=migration_summary["skipped"],
        created_shards=tuple(persistence_result.created_shards),
        removed_shards=tuple(persistence_result.removed_shards),
        updated_includes=persistence_result.updated_includes,
    )


def try_synchronize_authority_shards(project_root: Path) -> AuthoritySyncResult:
    """Best-effort shard synchronization for read-oriented commands.

    This function is intentionally non-interactive. It only writes when the current
    authority files are already writable. Locked authority remains protected, and
    the caller can still report the underlying drift or invalid authority state.

    Args:
        project_root: Root directory containing BPFW authority files.

    Returns:
        Synchronization result, including a skipped reason when writes were unsafe.
    """

    try:
        with authorize_blueprint_writes_for_tool("auto_reshard"):
            return synchronize_authority_shards(
                project_root=project_root,
                allow_large_migration=False,
            )
    except (
        AuthorityError,
        BlueprintLockedError,
        FileNotFoundError,
        ImportError,
        OSError,
        ValueError,
        yaml.YAMLError,
    ) as error:
        return AuthoritySyncResult(skipped_reason=str(error))
