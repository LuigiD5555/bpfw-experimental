"""Authority layout planner compatibility module.

The public authority planning names now live in ``bpfw.authority.layout``. This
module intentionally contains no automatic synchronization workflow and no write path.
"""

from bpfw.authority.layout import (
    BlockPlacementChange,
    BlueprintLayoutPlan,
    BlueprintLayoutPlanner,
)

__all__ = [
    "BlockPlacementChange",
    "BlueprintLayoutPlan",
    "BlueprintLayoutPlanner",
]
