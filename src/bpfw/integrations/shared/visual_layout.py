"""Reusable terminal layout helpers for interactive integrations."""

from dataclasses import dataclass
from typing import Sequence, TypeVar

from bpfw.integrations.shared.visual_boxes import render_box
from bpfw.integrations.shared.visual_theme import (
    DEFAULT_THEME,
    ThemeConfig,
    compute_panel_width,
    render_commands_box,
)


@dataclass(frozen=True)
class VisualPanel:
    """A boxed visual panel with optional command styling."""

    title: str
    lines: Sequence[str]
    role: str = "panel"


Item = TypeVar("Item")


def resolve_uniform_width(
    terminal_width: int,
    panels: Sequence[tuple[str, Sequence[str]] | VisualPanel],
    theme: ThemeConfig = DEFAULT_THEME,
) -> int:
    """Compute one shared width for several visual panels."""

    panel_widths = [
        compute_panel_width(
            content_lines=_panel_lines(panel),
            title=_panel_title(panel),
            terminal_width=terminal_width,
            theme=theme,
        )
        for panel in panels
    ]
    if not panel_widths:
        return compute_panel_width(
            content_lines=[],
            title="",
            terminal_width=terminal_width,
            theme=theme,
        )
    return max(panel_widths)


def render_visual_screen(
    panels: Sequence[VisualPanel],
    terminal_width: int,
    theme: ThemeConfig = DEFAULT_THEME,
    spacing: int = 1,
) -> list[str]:
    """Render stacked panels using one uniform adaptive width."""

    panel_width = resolve_uniform_width(
        terminal_width=terminal_width,
        panels=panels,
        theme=theme,
    )
    rendered_lines: list[str] = []
    for panel_index, panel in enumerate(panels):
        if panel_index > 0:
            rendered_lines.extend([""] * max(0, spacing))
        if panel.role == "commands":
            rendered_lines.extend(render_commands_box(lines=panel.lines, width=panel_width, theme=theme))
        else:
            rendered_lines.extend(render_box(title=panel.title, lines=list(panel.lines), width=panel_width))
    return rendered_lines


def limited_items(items: Sequence[Item], max_items: int) -> tuple[Sequence[Item], int]:
    """Return visible items and hidden count for large terminal lists."""

    if max_items < 0:
        return items, 0
    visible_items = items[:max_items]
    return visible_items, max(0, len(items) - len(visible_items))


def append_hidden_count(lines: list[str], hidden_count: int, noun: str) -> None:
    """Append a standard hidden-count line when a list is truncated."""

    if hidden_count > 0:
        lines.append(f"... {hidden_count} more {noun}")


def _panel_title(panel: tuple[str, Sequence[str]] | VisualPanel) -> str:
    if isinstance(panel, VisualPanel):
        return panel.title
    return panel[0]


def _panel_lines(panel: tuple[str, Sequence[str]] | VisualPanel) -> Sequence[str]:
    if isinstance(panel, VisualPanel):
        return panel.lines
    return panel[1]
