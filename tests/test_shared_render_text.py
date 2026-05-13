from bpfw.integrations.shared.render_text import center_text
from bpfw.integrations.shared.visual_theme import render_header


def test_center_text_width_behavior() -> None:
    assert center_text("hello", 3) == "hel"
    assert center_text("hello", 5) == "hello"
    assert center_text("hello", 9) == "  hello  "


def test_render_header_uses_centered_title_when_requested() -> None:
    width = 12
    lines = render_header("commands", width, centered=True)
    assert len(lines) == 3
    assert lines[1] == f"║{center_text('commands', width)}║"
