"""Package move grouping for repeated moved-code candidates."""

from dataclasses import dataclass
from pathlib import PurePosixPath

from bpfw.integrations.diff.models import DiffItem, DiffItemKind


@dataclass(frozen=True)
class PackageMoveGroup:
    """Represent a repeated path-prefix move as one human decision.

    Attributes:
        identifier: Stable group identifier for the current review snapshot.
        old_prefix: Old path prefix declared by authority.
        new_prefix: New path prefix found in real code.
        items: Moved-code items covered by this group.
    """

    identifier: str
    old_prefix: str
    new_prefix: str
    items: tuple[DiffItem, ...]


def group_package_moves(
    items: list[DiffItem],
    minimum_group_size: int = 2,
) -> tuple[list[PackageMoveGroup], list[DiffItem]]:
    """Group repeated moved-code candidates by path-prefix transformation.

    The grouping intentionally considers multiple possible prefix transforms per
    item and then selects the most useful non-overlapping groups. This prevents
    a broad transform such as ``src/bpfw/ -> src/bpfw/core/`` from swallowing a
    more precise package move such as
    ``src/bpfw/authority/ -> src/bpfw/core/authority/``.

    Args:
        items: Human-decision diff items.
        minimum_group_size: Minimum number of items required to form a group.

    Returns:
        Tuple of package move groups and ungrouped items.
    """
    candidate_groups: dict[tuple[str, str], list[DiffItem]] = {}
    initially_ungroupable: list[DiffItem] = []

    for item in items:
        prefix_pairs = _prefix_pairs_for_item(item)
        if not prefix_pairs:
            initially_ungroupable.append(item)
            continue
        for prefix_pair in prefix_pairs:
            candidate_groups.setdefault(prefix_pair, []).append(item)

    accepted_groups: list[PackageMoveGroup] = []
    used_item_ids: set[str] = set()
    ranked_candidates = sorted(
        (
            (prefix_pair, group_items)
            for prefix_pair, group_items in candidate_groups.items()
            if len(group_items) >= minimum_group_size
        ),
        key=lambda entry: _group_rank(entry[0], entry[1]),
        reverse=True,
    )

    for old_new_prefix, group_items in ranked_candidates:
        available_items = [
            item for item in group_items
            if item.identifier not in used_item_ids
        ]
        if len(available_items) < minimum_group_size:
            continue
        old_prefix, new_prefix = old_new_prefix
        accepted_groups.append(
            PackageMoveGroup(
                identifier=f"package-move-{len(accepted_groups) + 1}",
                old_prefix=old_prefix,
                new_prefix=new_prefix,
                items=tuple(sorted(available_items, key=lambda candidate: candidate.identifier)),
            )
        )
        used_item_ids.update(item.identifier for item in available_items)

    ungrouped_items = [
        item for item in items
        if item.identifier not in used_item_ids
    ]
    return accepted_groups, ungrouped_items


def _group_rank(prefix_pair: tuple[str, str], group_items: list[DiffItem]) -> tuple[int, int, int, int, str, str]:
    """Return a ranking tuple for package move group selection.

    Prefix pairs where the moved package name is preserved are preferred. For
    example, ``src/bpfw/authority/ -> src/bpfw/core/authority/`` is better
    than the broader ``src/bpfw/ -> src/bpfw/core/`` because the final package
    segment ``authority`` is preserved on both sides.

    Args:
        prefix_pair: Old and new prefix pair.
        group_items: Items covered by the pair.

    Returns:
        Ranking tuple where larger is better.
    """
    old_prefix, new_prefix = prefix_pair
    old_parts = PurePosixPath(old_prefix).parts
    new_parts = PurePosixPath(new_prefix).parts
    specificity = len(old_parts) + len(new_parts)
    affected = len(group_items)
    preserved_package_name = 1 if old_parts and new_parts and old_parts[-1] == new_parts[-1] else 0
    return preserved_package_name, affected * specificity, affected, specificity, old_prefix, new_prefix


def _prefix_pairs_for_item(item: DiffItem) -> list[tuple[str, str]]:
    """Return possible old/new prefix pairs for a groupable moved-code item.

    Args:
        item: Candidate item to inspect.

    Returns:
        Possible old/new prefix pairs ordered from more specific to broader.
    """
    if item.kind != DiffItemKind.MOVED_CODE_CANDIDATE:
        return []
    target = item.blueprint_target
    candidate = item.code_target or (item.candidates[0] if item.candidates else None)
    if target is None or candidate is None:
        return []
    if target.path is None or target.symbol is None or target.kind is None:
        return []
    if len(item.candidates) > 1:
        return []
    if target.symbol.split(".")[-1] != candidate.symbol.split(".")[-1]:
        return []
    if target.kind != candidate.kind:
        return []
    return _path_prefix_transforms(target.path, candidate.path)


def _path_prefix_transforms(old_path: str, new_path: str) -> list[tuple[str, str]]:
    """Find all meaningful prefix transformations that preserve a suffix.

    Args:
        old_path: Old declared path.
        new_path: Candidate path.

    Returns:
        Prefix pairs ordered from more specific to broader.
    """
    old_parts = PurePosixPath(old_path).parts
    new_parts = PurePosixPath(new_path).parts
    max_common_suffix_length = 0
    for old_part, new_part in zip(reversed(old_parts), reversed(new_parts)):
        if old_part != new_part:
            break
        max_common_suffix_length += 1
    if max_common_suffix_length == 0:
        return []

    pairs: list[tuple[str, str]] = []
    # Start with the shortest preserved suffix. That creates the most specific
    # prefix pair. Broader pairs are still emitted as fallbacks and may win when
    # they are genuinely the better repeated move.
    for suffix_length in range(1, max_common_suffix_length + 1):
        old_prefix_parts = old_parts[: len(old_parts) - suffix_length]
        new_prefix_parts = new_parts[: len(new_parts) - suffix_length]
        if not old_prefix_parts or not new_prefix_parts:
            continue
        old_prefix = "/".join(old_prefix_parts) + "/"
        new_prefix = "/".join(new_prefix_parts) + "/"
        if old_prefix == new_prefix:
            continue
        pair = (old_prefix, new_prefix)
        if pair not in pairs:
            pairs.append(pair)
    return pairs
