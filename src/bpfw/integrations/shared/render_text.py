"""PURPOSE shared text rendering small helpers used by visual helpers
DOMAIN  terminal UI
"""

from bpfw.integrations.shared.visual_width import display_width, fit_text


def center_text(text: str, width: int) -> str:
    """PURPOSE center plain text inside fixed width
    DOMAIN  terminal UI
    """

    text_width = display_width(text)
    if text_width >= width:
        return text[:width]
    remaining = width - text_width
    left_padding = remaining // 2
    right_padding = remaining - left_padding
    return (" " * left_padding) + text + (" " * right_padding)
