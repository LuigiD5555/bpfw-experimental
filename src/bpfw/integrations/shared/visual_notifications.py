"""Terminal notification rendering helpers for interactive integrations."""

from bpfw.integrations.shared.visual_boxes import _centered_title_bar
from bpfw.integrations.shared.visual_width import pad_text


def render_notification_block(
    title: str,
    lines: list[str],
    width: int,
) -> list[str]:
    """Render a terminal notification block as text lines."""

    top = f"╭{_centered_title_bar(title=title, width=width, fill='─')}╮"
    body = [f"│{pad_text(line, width)}│" for line in lines]
    bottom = "╰" + "─" * width + "╯"
    return [top, *body, bottom]