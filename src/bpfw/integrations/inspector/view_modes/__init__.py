"""PURPOSE inspector view mode registry
DOMAIN  inspector workflow
"""

from bpfw.integrations.inspector.view_modes.base import InspectorViewMode
from bpfw.integrations.inspector.view_modes.compact import CompactInspectorViewMode
from bpfw.integrations.inspector.view_modes.full import FullInspectorViewMode

COMPACT_VIEW_MODE = "compact"
FULL_VIEW_MODE = "full"


def resolve_inspector_view_mode(mode_name: str) -> InspectorViewMode:
    """PURPOSE get the inspector view mode matching a stable mode name
    DOMAIN  inspector workflow
    """

    normalized_mode_name = mode_name.strip().lower()
    if normalized_mode_name == FULL_VIEW_MODE:
        return FullInspectorViewMode()
    return CompactInspectorViewMode()


def resolve_inspector_view_mode_from_flag(show_all: bool) -> InspectorViewMode:
    """PURPOSE get the inspector view mode matching the terminal command display flag
    DOMAIN  inspector workflow
    """

    if show_all:
        return FullInspectorViewMode()
    return CompactInspectorViewMode()
