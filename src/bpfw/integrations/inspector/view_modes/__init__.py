"""Inspector view mode registry."""

from bpfw.integrations.inspector.view_modes.base import InspectorViewMode
from bpfw.integrations.inspector.view_modes.compact import CompactInspectorViewMode
from bpfw.integrations.inspector.view_modes.full import FullInspectorViewMode

COMPACT_VIEW_MODE = "compact"
FULL_VIEW_MODE = "full"


def resolve_inspector_view_mode(mode_name: str) -> InspectorViewMode:
    """Return the inspector view mode matching a stable mode name."""

    normalized_mode_name = mode_name.strip().lower()
    if normalized_mode_name == FULL_VIEW_MODE:
        return FullInspectorViewMode()
    return CompactInspectorViewMode()


def resolve_inspector_view_mode_from_flag(show_all: bool) -> InspectorViewMode:
    """Return the inspector view mode matching the CLI display flag."""

    if show_all:
        return FullInspectorViewMode()
    return CompactInspectorViewMode()
