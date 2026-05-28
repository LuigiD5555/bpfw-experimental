"""PURPOSE terminal box rendering helpers for interactive tools
DOMAIN  terminal UI
"""

from typing import List

from bpfw.integrations.shared.visual_width import display_width, fit_text, measure_lines, pad_text

COLUMN_GAP_WIDTH = 1
MIN_TEXT_RIGHT_PADDING = 1


def _centered_title_bar(title: str, width: int, fill: str = "─") -> str:
    """PURPOSE build a centered title bar segment with symmetric fill
    DOMAIN  terminal UI
    """

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


def render_box(title: str, lines: list[str], width: int) -> list[str]:
    """PURPOSE build a bordered section with a title and text lines
    DOMAIN  terminal UI
    """

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
    """PURPOSE show a two-column box using dynamically calculated widths
    DOMAIN  terminal UI
    """

    available_width = max(2, total_width - COLUMN_GAP_WIDTH)
    left_required = max(display_width(left_title) + 2, measure_lines(left_lines) + MIN_TEXT_RIGHT_PADDING)
    right_required = max(display_width(right_title) + 2, measure_lines(right_lines) + MIN_TEXT_RIGHT_PADDING)
    left_width, right_width = _resolve_two_column_widths(
        available_width=available_width,
        left_required=left_required,
        right_required=right_required,
        preferred_left_ratio=preferred_left_ratio,
        min_column_width=8,
    )

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
    """PURPOSE show a two-column terminal box with independent visual emphasis
    DOMAIN  terminal UI
    """

    available_width = max(2, total_width - COLUMN_GAP_WIDTH)
    left_required = max(display_width(left_title) + 3, measure_lines(left_lines) + MIN_TEXT_RIGHT_PADDING)
    right_required = max(display_width(right_title) + 3, measure_lines(right_lines) + MIN_TEXT_RIGHT_PADDING)
    left_width, right_width = _resolve_two_column_widths(
        available_width=available_width,
        left_required=left_required,
        right_required=right_required,
        preferred_left_ratio=preferred_left_ratio,
        min_column_width=12,
    )

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


def _resolve_two_column_widths(
    available_width: int,
    left_required: int,
    right_required: int,
    preferred_left_ratio: float,
    min_column_width: int,
) -> tuple[int, int]:
    """PURPOSE find column widths without truncating when the total width can fit
    DOMAIN  terminal UI
    """

    available_width = max(2, available_width)
    if left_required + right_required <= available_width:
        preferred_left_width = int(available_width * preferred_left_ratio)
        spare_width = available_width - left_required - right_required
        left_extra = min(spare_width, max(0, preferred_left_width - left_required))
        left_width = left_required + left_extra
        return left_width, available_width - left_width

    effective_min_width = min(min_column_width, max(1, available_width // 2))
    maximum_left_width = max(effective_min_width, available_width - effective_min_width)
    preferred_left_width = int(available_width * preferred_left_ratio)
    left_width = min(max(preferred_left_width, effective_min_width), maximum_left_width)
    return left_width, available_width - left_width
