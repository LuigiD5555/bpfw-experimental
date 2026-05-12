from bpfw.integrations.shared.visual_layout import (
    VisualPanel,
    append_hidden_count,
    limited_items,
    render_visual_screen,
    resolve_uniform_width,
)


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


def test_limited_items_and_hidden_count_line() -> None:
    visible, hidden_count = limited_items([1, 2, 3], max_items=2)
    lines = [str(item) for item in visible]

    append_hidden_count(lines, hidden_count, "items")

    assert lines == ["1", "2", "... 1 more items"]
