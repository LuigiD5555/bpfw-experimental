"""Shared theme and primitive render helpers for interactive integrations."""

from dataclasses import dataclass
from typing import Iterable, List, Sequence

from bpfw.integrations.shared.render_text import center_text
from bpfw.integrations.shared.visual_width import display_width, fit_text, measure_lines, pad_text


@dataclass(frozen=True)
class ThemeConfig:
    """Theme settings shared by inspector, editor and planner."""

    min_ratio: float = 0.50
    max_ratio: float = 0.95
    horizontal_padding: int = 0
    title_fill: str = "─"


DEFAULT_THEME = ThemeConfig()
COMMAND_LEFT_PADDING = 1


def compute_panel_width(
    content_lines: Sequence[str],
    title: str,
    terminal_width: int,
    theme: ThemeConfig = DEFAULT_THEME,
) -> int:
    """Return adaptive panel width constrained by theme min/max ratios."""

    minimum_width = max(20, int(terminal_width * theme.min_ratio) - 2)
    maximum_width = max(minimum_width, int(terminal_width * theme.max_ratio) - 2)
    title_width = display_width(f" {title} ")
    content_width = measure_lines(list(content_lines)) if content_lines else 0
    required_width = max(title_width, content_width) + (theme.horizontal_padding * 2)
    return max(minimum_width, min(maximum_width, required_width))


def render_header(
    title: str,
    width: int,
    theme: ThemeConfig = DEFAULT_THEME,
    centered: bool = True,
) -> List[str]:
    """Render a standard integration header block."""

    if centered:
        title_line = center_text(title, width)
    else:
        title_line = pad_text(title, width)
    return [
        "╔" + "═" * width + "╗",
        f"║{pad_text(title_line, width)}║",
        "╚" + "═" * width + "╝",
    ]


def render_panel(
    title: str,
    lines: Sequence[str],
    width: int,
    theme: ThemeConfig = DEFAULT_THEME,
    centered_title: bool = True,
) -> List[str]:
    """Render a boxed panel with centered title by default."""

    label = f" {title} "
    if centered_title:
        title_bar = _center_fill(label=label, width=width, fill=theme.title_fill)
    else:
        title_bar = fit_text(label, width) + (theme.title_fill * max(0, width - display_width(fit_text(label, width))))
    body = [f"│{pad_text(line, width)}│" for line in lines]
    return [f"╭{title_bar}╮", *body, f"╰{'─' * width}╯"]


def render_commands_box(
    lines: Sequence[str],
    width: int,
    theme: ThemeConfig = DEFAULT_THEME,
    wrap_mode: str = "safe_wrap",
) -> List[str]:
    """Render commands panel with safe wrapping/truncation."""

    content_width = max(1, width - COMMAND_LEFT_PADDING)
    wrapped_lines: List[str] = []
    for line in lines:
        wrapped = _safe_wrap_line(line=line, width=content_width) if wrap_mode == "safe_wrap" else [fit_text(line, content_width)]
        wrapped_lines.extend(f"{' ' * COMMAND_LEFT_PADDING}{wrapped_line}" for wrapped_line in wrapped)
    return render_panel(title="Commands", lines=wrapped_lines, width=width, theme=theme, centered_title=True)


def render_stacked_sections(sections: Sequence[Sequence[str]], spacing: int = 1) -> List[str]:
    """Stack rendered sections with configurable spacing."""

    stacked: List[str] = []
    for index, section in enumerate(sections):
        if index > 0:
            stacked.extend([""] * max(0, spacing))
        stacked.extend(section)
    return stacked


def _safe_wrap_line(line: str, width: int) -> List[str]:
    """Wrap by words and truncate long tokens without breaking box width."""

    if width <= 0:
        return [""]
    words = line.split(" ")
    if not words:
        return [""]

    chunks: List[str] = []
    current = ""
    for word in words:
        token = word if display_width(word) <= width else fit_text(word, width)
        if not current:
            current = token
            continue
        candidate = f"{current} {token}"
        if display_width(candidate) <= width:
            current = candidate
            continue
        chunks.append(current)
        current = token
    if current:
        chunks.append(current)
    return chunks or [fit_text(line, width)]


def _center_fill(label: str, width: int, fill: str) -> str:
    """Center label with symmetric fill."""

    label_width = display_width(label)
    if label_width >= width:
        return fit_text(label, width)
    remaining = width - label_width
    left = remaining // 2
    right = remaining - left
    return (fill * left) + label + (fill * right)
