"""Tests for grouped package move drift decisions."""

from pathlib import Path

from bpfw.integrations.diff.models import (
    BlueprintTarget,
    CodeTarget,
    DiffActionLevel,
    DiffItem,
    DiffItemKind,
    DiffRisk,
)
from bpfw.integrations.diff.package_moves import group_package_moves


def _moved_item(relative_path: str, symbol: str) -> DiffItem:
    """Build one moved-code item for package grouping tests.

    Args:
        relative_path: Relative file suffix preserved by the move.
        symbol: Symbol name.

    Returns:
        Diff item.
    """
    old_path = f"src/pkg/old/{relative_path}"
    new_path = f"src/pkg/new/{relative_path}"
    return DiffItem(
        identifier=f"moved-{symbol}",
        kind=DiffItemKind.MOVED_CODE_CANDIDATE,
        action_level=DiffActionLevel.HUMAN_DECISION,
        risk=DiffRisk.HIGH,
        reason="Possible moved code.",
        blueprint_target=BlueprintTarget(
            block_id=symbol,
            path=old_path,
            symbol=symbol,
            kind="class",
            source_shard_path=Path("bpfw/blocks/core.yaml"),
        ),
        code_target=CodeTarget(path=new_path, symbol=symbol, kind="class"),
        candidates=(CodeTarget(path=new_path, symbol=symbol, kind="class"),),
    )


def test_group_package_moves_collapses_repeated_prefix_transform() -> None:
    """Repeated old-prefix to new-prefix moves should become one group."""
    items = [
        _moved_item("document.py", "AuthorityDocument"),
        _moved_item("repository.py", "AuthorityRepository"),
        _moved_item("patch/engine.py", "AuthorityPatchEngine"),
    ]

    groups, ungrouped = group_package_moves(items)

    assert len(groups) == 1
    assert not ungrouped
    assert groups[0].old_prefix == "src/pkg/old/"
    assert groups[0].new_prefix == "src/pkg/new/"
    assert len(groups[0].items) == 3


def test_group_package_moves_keeps_singletons_ungrouped() -> None:
    """A single moved candidate should remain an individual decision."""
    groups, ungrouped = group_package_moves([_moved_item("document.py", "AuthorityDocument")])

    assert not groups
    assert len(ungrouped) == 1


def _core_insert_item(folder: str, relative_path: str, symbol: str) -> DiffItem:
    """Build one item for src/bpfw/<folder> to src/bpfw/core/<folder> moves.

    Args:
        folder: Package folder moved under core.
        relative_path: File path relative to the folder.
        symbol: Symbol name.

    Returns:
        Diff item.
    """
    old_path = f"src/bpfw/{folder}/{relative_path}"
    new_path = f"src/bpfw/core/{folder}/{relative_path}"
    return DiffItem(
        identifier=f"moved-{folder}-{symbol}",
        kind=DiffItemKind.MOVED_CODE_CANDIDATE,
        action_level=DiffActionLevel.HUMAN_DECISION,
        risk=DiffRisk.HIGH,
        reason="Possible moved code.",
        blueprint_target=BlueprintTarget(
            block_id=symbol,
            path=old_path,
            symbol=symbol,
            kind="class",
            source_shard_path=Path("bpfw/blocks/core.yaml"),
        ),
        code_target=CodeTarget(path=new_path, symbol=symbol, kind="class"),
        candidates=(CodeTarget(path=new_path, symbol=symbol, kind="class"),),
    )


def test_group_package_moves_prefers_specific_preserved_package_prefixes() -> None:
    """Grouping should prefer package-specific prefixes over broad root moves."""
    items = [
        _core_insert_item("authority", "document.py", "AuthorityDocument"),
        _core_insert_item("authority", "repository.py", "AuthorityRepository"),
        _core_insert_item("authority", "patch/engine.py", "AuthorityPatchEngine"),
        _core_insert_item("catalog", "loader.py", "CatalogLoader"),
        _core_insert_item("catalog", "drift.py", "CatalogDrift"),
    ]

    groups, ungrouped = group_package_moves(items)

    prefix_pairs = {(group.old_prefix, group.new_prefix): len(group.items) for group in groups}
    assert prefix_pairs == {
        ("src/bpfw/authority/", "src/bpfw/core/authority/"): 3,
        ("src/bpfw/catalog/", "src/bpfw/core/catalog/"): 2,
    }
    assert not ungrouped
