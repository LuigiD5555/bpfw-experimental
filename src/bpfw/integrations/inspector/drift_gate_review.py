"""Pure review-queue construction for Drift Gate."""

from __future__ import annotations

from dataclasses import dataclass

from bpfw.integrations.diff.models import DiffItem
from bpfw.integrations.diff.package_moves import PackageMoveGroup


@dataclass(slots=True)
class DriftReviewEntry:
    """One linear Drift Gate review entry."""

    kind: str
    items: list[DiffItem]
    group: PackageMoveGroup | None = None
    item: DiffItem | None = None


def build_review_entries(
    package_groups: list[PackageMoveGroup],
    ungrouped_items: list[DiffItem],
) -> list[DriftReviewEntry]:
    """Build the package-first linear review queue."""
    entries = [
        DriftReviewEntry(kind="package", group=group, items=list(group.items))
        for group in package_groups
    ]
    entries.extend(
        DriftReviewEntry(kind="item", item=item, items=[item])
        for item in ungrouped_items
    )
    return entries


def remaining_items_after_entry(
    review_entries: list[DriftReviewEntry],
    next_entry_index: int,
) -> list[DiffItem]:
    """Flatten diff items belonging to entries not yet reviewed."""
    remaining: list[DiffItem] = []
    for entry in review_entries[next_entry_index:]:
        remaining.extend(entry.items)
    return remaining
