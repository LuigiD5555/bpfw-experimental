"""Common Lego kit for interactive integrations (inspector, editor, planner)."""

from bpfw.integrations.shared.visual_width import (
    display_width,
    fit_text,
    pad_text,
    measure_lines,
)
from bpfw.integrations.shared.visual_boxes import (
    render_box,
    render_two_column_box,
    render_split_box,
)
from bpfw.integrations.shared.visual_notifications import render_notification_block
from bpfw.integrations.shared.visual_theme import (
    ThemeConfig,
    DEFAULT_THEME,
    compute_panel_width,
    render_header,
    render_panel,
    render_commands_box,
    render_stacked_sections,
)
from bpfw.integrations.shared.navigation import NavigationAction

__all__ = [
    # visual_width
    "display_width",
    "fit_text",
    "pad_text",
    "measure_lines",
    # visual_boxes
    "render_box",
    "render_two_column_box",
    "render_split_box",
    # visual_notifications
    "render_notification_block",
    # visual_theme
    "ThemeConfig",
    "DEFAULT_THEME",
    "compute_panel_width",
    "render_header",
    "render_panel",
    "render_commands_box",
    "render_stacked_sections",
    # navigation
    "NavigationAction",
]
