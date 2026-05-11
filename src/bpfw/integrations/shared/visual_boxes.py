"""Terminal box rendering helpers for interactive integrations."""

from typing import List

from bpfw.integrations.shared.visual_width import (
    display_width,
    fit_text,
    pad_text,
    measure_lines,
)

COLUMN_GAP_WIDTH = 1


def _centered_title_bar(title: str, width: int, fill: str = "─") -> str:
    """Build a centered title bar segment with symmetric fill."""

    if not title.strip():
        return fill * width
    label = f" {title} "
    label_width = display_width(label)
    if label_width >= width:
        return fit_text(label, width)
    remaining = width - label_width
    left_fill = remaining // 2
    right_fill = remaining - left_fill
    return (fill * left_fill) + label + (fill * right_fill)


def _center_text(text: str, width: int) -> str:
    """Center plain text inside fixed width."""

    text_width = display_width(text)
    if text_width >= width:
        return fit_text(text, width)
    remaining = width - text_width
    left_padding = remaining // 2
    right_padding = remaining - left_padding
    return (" " * left_padding) + text + (" " * right_padding)


def render_box(title: str, lines: list[str], width: int) -> list[str]:
    """Build a bordered section with a title and text lines."""

    top = f"╭{_centered_title_bar(title=title, width=width, fill='─')}╮"
    body = [f"│{pad_text(line, width)}│" for line in lines]
    bottom = "╰" + "─" * width + "╯"
    return [top, *body, bottom]


def render_two_column_box(
    left_title: str,
    left_lines: List[str],
    right_title: str,
    right_lines: List[str],
    total_width: int,
    preferred_left_ratio: float = 0.5,
) -> List[str]:
    """Render a two-column box using dynamically calculated widths."""

    available_width = max(2, total_width - COLUMN_GAP_WIDTH)
    left_required = max(display_width(left_title) + 3, measure_lines(left_lines))
    right_required = max(display_width(right_title) + 3, measure_lines(right_lines))
    left_width = int(available_width * preferred_left_ratio)
    left_width = max(left_width, left_required)
    right_width = available_width - left_width
    min_column_width = 8
    if right_width < min_column_width:
        left_width = available_width // 2
        right_width = available_width - left_width
    if left_width < min_column_width:
        left_width = min_column_width
        right_width = max(min_column_width, available_width - left_width)

    left_top = _centered_title_bar(title=left_title, width=left_width, fill="─")
    right_top = _centered_title_bar(title=right_title, width=right_width, fill="─")
    lines = [f"╭{left_top}┬{right_top}╮"]
    row_count = max(len(left_lines), len(right_lines))
    for row_index in range(row_count):
        left_text = left_lines[row_index] if row_index < len(left_lines) else ""
        right_text = right_lines[row_index] if row_index < len(right_lines) else ""
        lines.append(f"│{pad_text(left_text, left_width)}│{pad_text(right_text, right_width)}│")
    lines.append(f"╰{'─' * left_width}┴{'─' * right_width}╯")
    return lines


def render_split_box(
    left_title: str,
    left_lines: list[str],
    right_title: str,
    right_lines: list[str],
    total_width: int,
    left_border_fill: str = "═",
    right_border_fill: str = "─",
    preferred_left_ratio: float = 0.5,
) -> list[str]:
    """Render a two-column terminal box with independent visual emphasis."""

    available_width = max(2, total_width - COLUMN_GAP_WIDTH)
    left_required = max(display_width(left_title) + 3, measure_lines(left_lines))
    right_required = max(display_width(right_title) + 3, measure_lines(right_lines))
    left_width = int(available_width * preferred_left_ratio)
    left_width = max(left_width, left_required)
    right_width = available_width - left_width
    min_column_width = 12
    if right_width < min_column_width:
        left_width = available_width - min_column_width
        right_width = min_column_width
    if left_width < min_column_width:
        left_width = min_column_width
        right_width = available_width - left_width

    left_top = _centered_title_bar(title=left_title, width=left_width, fill=left_border_fill)
    right_top = _centered_title_bar(title=right_title, width=right_width, fill=right_border_fill)

    lines = [f"╔{left_top}╦{right_top}╮"]
    row_count = max(len(left_lines), len(right_lines))
    for row_index in range(row_count):
        left_text = left_lines[row_index] if row_index < len(left_lines) else ""
        right_text = right_lines[row_index] if row_index < len(right_lines) else ""
        lines.append(f"║{pad_text(left_text, left_width)}║{pad_text(right_text, right_width)}│")
    lines.append(f"╚{'═' * left_width}╩{'─' * right_width}╯")
    return lines
