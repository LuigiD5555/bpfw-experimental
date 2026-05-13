"""Shared text rendering primitives used by visual helpers."""

from bpfw.integrations.shared.visual_width import display_width, fit_text


def center_text(text: str, width: int) -> str:
    """Center plain text inside fixed width."""

    text_width = display_width(text)
    if text_width >= width:
        return fit_text(text, width)
    remaining = width - text_width
    left_padding = remaining // 2
    right_padding = remaining - left_padding
    return (" " * left_padding) + text + (" " * right_padding)
