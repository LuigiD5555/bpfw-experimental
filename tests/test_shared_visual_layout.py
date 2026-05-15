from bpfw.integrations.shared.visual_layout import (
    VisualPanel,
    append_hidden_count,
    limited_items,
    render_visual_screen,
    resolve_uniform_width,
)
from bpfw.integrations.shared.visual_boxes import render_two_column_box
from bpfw.integrations.shared.visual_theme import render_commands_box
from bpfw.integrations.shared.visual_width import display_width


def test_resolve_uniform_width_uses_largest_panel() -> None:
    width = resolve_uniform_width(
        terminal_width=100,
        panels=[
            ("Short", ["one"]),
            ("Long", ["this line needs more room"]),
        ],
    )

    assert width >= len("this line needs more room")


def test_render_visual_screen_uses_command_panel_style() -> None:
    output = render_visual_screen(
        terminal_width=100,
        panels=[
            VisualPanel(title="Tool", lines=["Body"]),
            VisualPanel(title="Actions", lines=["[b] Back"], role="commands"),
        ],
    )
    text = "\n".join(output)

    assert "Tool" in text
    assert "Commands" in text
    assert "[b] Back" in text
    assert "│ [b] Back" in text


def test_render_commands_box_adds_left_inset() -> None:
    output = render_commands_box(lines=["[q] Quit"], width=20)

    assert "│ [q] Quit" in "\n".join(output)


def test_limited_items_and_hidden_count_line() -> None:
    visible, hidden_count = limited_items([1, 2, 3], max_items=2)
    lines = [str(item) for item in visible]

    append_hidden_count(lines, hidden_count, "items")

    assert lines == ["1", "2", "... 1 more items"]


def test_two_column_box_uses_required_width_before_ratio() -> None:
    rendered = render_two_column_box(
        left_title="Domain suggestions",
        left_lines=[" [a] protection"],
        right_title="Purpose suggestions",
        right_lines=[" [4] Resolve project blueprint path safely"],
        total_width=64,
        preferred_left_ratio=0.45,
    )

    text = "\n".join(rendered)

    assert "Resolve project blueprint path safely" in text
    assert "…" not in text
    assert all(display_width(line) == 66 for line in rendered)


def test_two_column_box_keeps_space_after_longest_text() -> None:
    text = " [4] Resolve project blueprint path safely"
    rendered = render_two_column_box(
        left_title="Domain suggestions",
        left_lines=[" [q] protection"],
        right_title="Purpose suggestions",
        right_lines=[text],
        total_width=64,
        preferred_left_ratio=0.45,
    )

    assert f"{text} │" in "\n".join(rendered)


def test_two_column_box_keeps_total_width_when_content_overflows() -> None:
    rendered = render_two_column_box(
        left_title="Domain suggestions",
        left_lines=[" [a] " + "domain " * 10],
        right_title="Purpose suggestions",
        right_lines=[" [4] " + "purpose " * 10],
        total_width=30,
        preferred_left_ratio=0.45,
    )

    assert any("…" in line for line in rendered)
    assert all(display_width(line) == 32 for line in rendered)


def test_render_commands_box_supports_divider_line() -> None:
    output = render_commands_box(lines=["[q] Quit", "__BPFW_COMMAND_SEPARATOR__", "Note: press Enter"], width=24)
    text = "\n".join(output)

    assert "├" in text
    assert "┤" in text
    assert "Note: press Enter" in text
