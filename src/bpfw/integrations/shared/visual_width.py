"""Terminal text width helpers for interactive integrations."""

import unicodedata

ELLIPSIS = "…"


def display_width(text: str) -> int:
    """Return the visible terminal column width for text."""

    width = 0
    for character in text:
        if unicodedata.combining(character):
            continue
        width += 2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1
    return width


def fit_text(text: str, width: int) -> str:
    """Fit text into fixed terminal width, truncating with ellipsis when needed."""

    if width <= 0:
        return ""
    if display_width(text) <= width:
        return text
    if width == 1:
        return ELLIPSIS

    result = ""
    consumed = 0
    budget = width - display_width(ELLIPSIS)
    for character in text:
        char_width = 0 if unicodedata.combining(character) else (
            2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1
        )
        if consumed + char_width > budget:
            break
        result += character
        consumed += char_width
    return result + ELLIPSIS


def pad_text(text: str, width: int) -> str:
    """Pad text to a fixed terminal display width."""

    fitted = fit_text(text, width)
    return fitted + (" " * max(0, width - display_width(fitted)))


def measure_lines(lines: list[str]) -> int:
    """Return the maximum display width required by the given lines."""

    if not lines:
        return 0
    return max(display_width(line) for line in lines)