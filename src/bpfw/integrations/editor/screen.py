"""Terminal screen control and input helpers for BPFW Editor."""

import shutil
import sys
import termios
import tty

from bpfw.integrations.shared.cli_runtime import QUIT_COMMAND, QUIT_COMMAND_KEY, quit_command_label
from bpfw.integrations.shared.visual_boxes import render_box
from bpfw.integrations.shared.screen_control import refresh_screen
from bpfw.integrations.shared.visual_theme import (
    DEFAULT_THEME,
    compute_panel_width,
    render_commands_box,
    render_header,
)


DEFAULT_INPUT_PROMPT = "> "


def clear_screen() -> None:
    """Clear the terminal screen using ANSI escape codes."""
    refresh_screen()


def get_terminal_width() -> int:
    """Return terminal width with a safe minimum."""

    try:
        return shutil.get_terminal_size((80, 24)).columns
    except (ValueError, OSError):
        return 80


def get_terminal_height() -> int:
    """Return terminal height with a safe minimum."""

    try:
        return shutil.get_terminal_size((80, 24)).lines
    except (ValueError, OSError):
        return 24


def _normalize_prompt(prompt: str) -> str:
    """Return the visible editor prompt for input-ready states."""

    return prompt or DEFAULT_INPUT_PROMPT


def read_input(prompt: str = DEFAULT_INPUT_PROMPT) -> str:
    """Read a line of input, returning stripped value."""

    try:
        value = input(_normalize_prompt(prompt))
        return value.strip()
    except (EOFError, KeyboardInterrupt):
        return QUIT_COMMAND


def read_line(prompt: str = DEFAULT_INPUT_PROMPT) -> str:
    """Read a single line of input with a prompt."""

    try:
        value = input(_normalize_prompt(prompt))
        return value.rstrip("\n")
    except (EOFError, KeyboardInterrupt):
        return ""


def wait_for_enter() -> None:
    """Wait for the user to press Enter."""

    try:
        print("Press Enter to continue.")
        input(DEFAULT_INPUT_PROMPT)
    except (EOFError, KeyboardInterrupt):
        pass


def paginate_items(items: list, page: int, page_size: int = 20) -> tuple[list, int, int, int]:
    """Return a page of items and pagination metadata.

    Returns:
        (page_items, start_index, end_index, total_count)
    """

    total = len(items)
    start = (page - 1) * page_size
    end = min(start + page_size, total)

    if start >= total:
        return [], 0, 0, total

    return items[start:end], start + 1, end, total


def format_paging_footer(start: int, end: int, total: int) -> str:
    """Format a pagination status line."""

    if total == 0:
        return "Showing 0 items"
    return f"Showing {start}-{end} of {total}"


def truncate(text: str, max_width: int) -> str:
    """Truncate text to fit within max_width, adding ellipsis if needed."""

    if len(text) <= max_width:
        return text
    if max_width < 4:
        return text[:max_width]
    return text[: max_width - 3] + "..."


def read_multiline() -> list[str]:
    """Read multiple lines until an empty line is entered.

    Returns:
        List of non-empty lines.
    """

    lines = []
    try:
        while True:
            line = input(DEFAULT_INPUT_PROMPT)
            if line.strip() == "":
                break
            lines.append(line.rstrip("\n"))
    except (EOFError, KeyboardInterrupt):
        pass

    return lines


def read_key() -> str:
    """Read a single keystroke from stdin.

    Returns:
        Single character or special key name.

    Special keys:
        - 'up', 'down', 'left', 'right' for arrow keys
        - 'enter' for Enter/Return key
        - 'escape' for Esc key
        - 'space' for Space key
        - 'tab' for Tab key
    """
    try:
        # Save terminal settings
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)

        # Set terminal to raw mode for single key input
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)

            # Handle special keys (arrow keys, etc.)
            if ch == '\x1b':  # ESC sequence
                ch2 = sys.stdin.read(1) if sys.stdin.read(1) else ''
                if ch2 == '[':
                    ch3 = sys.stdin.read(1) if sys.stdin.read(1) else ''
                    if ch3 == 'A':
                        return 'up'
                    elif ch3 == 'B':
                        return 'down'
                    elif ch3 == 'C':
                        return 'right'
                    elif ch3 == 'D':
                        return 'left'
                    elif ch3 == 'Z':  # Shift+Tab
                        return 'shift_tab'
                elif ch2 == '\x1b':  # Double ESC - actual ESC key
                    return 'escape'
                return 'escape'
            elif ch == '\r' or ch == '\n':
                return 'enter'
            elif ch == ' ':
                return 'space'
            elif ch == '\t':
                return 'tab'
            elif ch == '\x7f' or ch == '\x08':  # Backspace/Delete
                return 'backspace'
            elif ch == '\x03':  # Ctrl+C
                raise KeyboardInterrupt
            elif ch == '\x04':  # Ctrl+D
                raise EOFError
            else:
                return ch.lower()  # Return lowercase version
        finally:
            # Restore terminal settings
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    except (termios.error, OSError, AttributeError):
        # Fallback for non-Unix systems or when terminal control fails
        # Read line and return first character
        try:
            line = input()
            if line:
                first_char = line[0].lower()
                if first_char == '\r' or first_char == '\n':
                    return 'enter'
                elif first_char == ' ':
                    return 'space'
                elif first_char == '\t':
                    return 'tab'
                return first_char
            return 'enter'
        except (EOFError, KeyboardInterrupt):
            if isinstance(sys.last_type, KeyboardInterrupt):
                raise
            return QUIT_COMMAND


# ---------------------------------------------------------------------------
# Editor search-first UI rendering
# ---------------------------------------------------------------------------

BANNER_TITLE = "Blueprint Framework Editor"


def _editor_block_width(ratio: float = 0.70) -> int:
    """Return a consistent width for editor blocks."""

    terminal_width = get_terminal_width()
    preferred_width = max(20, int(terminal_width * ratio) - 2)
    minimum_width = max(20, int(terminal_width * DEFAULT_THEME.min_ratio) - 2)
    maximum_width = max(minimum_width, int(terminal_width * DEFAULT_THEME.max_ratio) - 2)
    return max(minimum_width, min(maximum_width, preferred_width))


def _results_block_ratio(results: list) -> float:
    """Return dynamic width ratio (70%-95%) based on CODE content size."""

    if not results:
        return 0.70

    max_code_length = max(len((record.location or "")) for record in results)
    min_ratio = 0.70
    max_ratio = 0.95
    min_length = 24
    max_length = 120

    if max_code_length <= min_length:
        return min_ratio
    if max_code_length >= max_length:
        return max_ratio

    growth_fraction = (max_code_length - min_length) / (max_length - min_length)
    return min_ratio + (max_ratio - min_ratio) * growth_fraction


def render_editor_banner(ratio: float = 0.70) -> None:
    """Print the editor banner at the top of the screen."""

    banner_width = _editor_block_width(ratio=ratio)
    for line in render_header(title=BANNER_TITLE, width=banner_width, theme=DEFAULT_THEME, centered=True):
        print(line)


def render_search_screen() -> None:
    """Render the initial search prompt screen."""

    clear_screen()
    render_editor_banner()
    print()
    _render_search_scope_box(
        title="Search block to inspect",
        lines=[
            " Search by:",
            "   id, name, domain, purpose, lifecycle, path or symbol",
        ],
    )
    print()
    _render_examples_box(
        [
            " loader",
            " catalog",
            " active",
            " deprecated",
            " blueprint validation",
        ],
    )
    print()


def render_results_table(
    results: list,
    query: str,
    filter_display_lines: list[str],
) -> None:
    """Render the search results screen with a table and command menu.

    results: list of SearchRecord
    filter_display_lines: display lines from FilterState
    """

    block_ratio = _results_block_ratio(results)
    clear_screen()
    render_editor_banner(ratio=block_ratio)
    print()
    print(" Search:")
    print(f"   {query or 'all'}")
    print()

    if not results:
        print(" No blocks found.")
        print()
        _render_filter_display(filter_display_lines)
        print()
        _render_empty_commands(ratio=block_ratio)
        return

    _render_results_table_rows(results, ratio=block_ratio)
    print()
    _render_filter_display(filter_display_lines)
    print()
    _render_results_commands(ratio=block_ratio)


def _render_results_table_rows(results: list, ratio: float = 0.70) -> None:
    """Render the actual table of search results."""

    width = _editor_block_width(ratio=ratio)

    # Five columns need six vertical separators.
    total_content_width = max(54, width - 6)
    idx_width = 5
    # Keep CODE narrower so the other columns can breathe.
    code_width = max(18, min(36, total_content_width // 3))
    remaining_width = total_content_width - idx_width - code_width

    # Redistribute remaining width with NAME slightly wider.
    status_width = max(10, int(remaining_width * 0.28))
    domain_width = max(10, int(remaining_width * 0.28))
    name_width = max(14, remaining_width - status_width - domain_width)

    # Header
    header = (
        f"\u2502{'IDX':^{idx_width}}"
        f"\u2502{'LIFECYCLE':^{status_width}}"
        f"\u2502{'DOMAIN':^{domain_width}}"
        f"\u2502{'NAME':^{name_width}}"
        f"\u2502{'CODE':^{code_width}}\u2502"
    )
    separator = (
        f"\u251c{'\u2500' * idx_width}"
        f"\u253c{'\u2500' * status_width}"
        f"\u253c{'\u2500' * domain_width}"
        f"\u253c{'\u2500' * name_width}"
        f"\u253c{'\u2500' * code_width}\u2524"
    )
    top_border = (
        f"\u250c{'\u2500' * idx_width}"
        f"\u252c{'\u2500' * status_width}"
        f"\u252c{'\u2500' * domain_width}"
        f"\u252c{'\u2500' * name_width}"
        f"\u252c{'\u2500' * code_width}\u2510"
    )
    bottom_border = (
        f"\u2514{'\u2500' * idx_width}"
        f"\u2534{'\u2500' * status_width}"
        f"\u2534{'\u2500' * domain_width}"
        f"\u2534{'\u2500' * name_width}"
        f"\u2534{'\u2500' * code_width}\u2518"
    )

    print(top_border)
    print(header)
    print(separator)

    for display_index, record in enumerate(results, start=1):
        status = truncate(record.status or "-", status_width).center(status_width)
        domain = truncate(record.domain or "-", domain_width).center(domain_width)
        name = truncate(record.name or "-", name_width).ljust(name_width)
        record_location = record.location or "-"
        code = truncate(record_location, code_width).ljust(code_width)
        index_str = str(display_index).center(idx_width)
        print(f"\u2502{index_str}\u2502{status}\u2502{domain}\u2502{name}\u2502{code}\u2502")
        if code.strip() != record_location:
            print(f"  location: {record_location}")

    print(bottom_border)


def _render_filter_display(filter_display_lines: list[str]) -> None:
    """Render active filters section."""

    print(" Active filters:")
    for line in filter_display_lines:
        print(f"   {line}")


def _render_results_commands(ratio: float = 0.70) -> None:
    """Render command menu for results screen."""

    lines = [
        "[idx] inspect             [f] filter               [h] help",
        f"[/] search again          [c] clear filters        {quit_command_label()}",
        "[a] show all",
    ]
    _render_editor_commands_box(lines, ratio=ratio)


def _render_empty_commands(ratio: float = 0.70) -> None:
    """Render command menu when no results found."""

    lines = [
        "[/] search again          [c] clear filters        [h] help",
        f"[a] show all              {quit_command_label()}",
    ]
    _render_editor_commands_box(lines, ratio=ratio)


def _render_editor_commands_box(lines: list[str], ratio: float = 0.70) -> None:
    """Render editor commands using inspector-style command box."""

    width = _editor_block_width(ratio=ratio)
    for line in render_commands_box(lines=lines, width=width, theme=DEFAULT_THEME, wrap_mode="safe_wrap"):
        print(line)


def render_filter_screen() -> None:
    """Render the filter input screen."""

    clear_screen()
    render_editor_banner()
    print()
    print(" Add Filter")
    print()
    print(" Available columns:")
    print("   status")
    print("   domain")
    print("   name")
    print("   path")
    print()
    _render_examples_box(
        [
            " status=active",
            " domain=catalog",
            " name=loader",
            " path=editor",
        ],
    )
    print()


def _render_examples_box(example_lines: list[str], ratio: float = 0.70) -> None:
    """Render examples in a boxed multiline section."""

    width = compute_panel_width(
        content_lines=example_lines,
        title="Examples",
        terminal_width=get_terminal_width(),
        theme=DEFAULT_THEME,
    )
    for line in render_box(title="Examples", lines=example_lines, width=width):
        print(line)


def _render_search_scope_box(title: str, lines: list[str], ratio: float = 0.70) -> None:
    """Render search scope details in a boxed section."""

    width = compute_panel_width(
        content_lines=lines,
        title=title,
        terminal_width=get_terminal_width(),
        theme=DEFAULT_THEME,
    )
    for line in render_box(title=title, lines=lines, width=width):
        print(line)


def render_invalid_selection() -> None:
    """Render invalid IDX selection message."""

    print()
    print(" Invalid selection.")
    print()
    print(" Choose an IDX from the table, or use:")
    print("   /      search again")
    print("   f      filter")
    print("   c      clear filters")
    print("   a      show all")
    print("   h      help")
    print(f"   {QUIT_COMMAND_KEY:<6} quit")


def render_filter_error(message: str) -> None:
    """Render a filter error message."""

    print()
    print(message)


def render_editor_help_screen() -> None:
    """Render the editor help screen."""

    clear_screen()
    print("╭───────────────────────────── Editor help ──────────────────────────────╮")
    print("│                                                                         │")
    print("│  Search                                                                 │")
    print("│  ──────                                                                 │")
    print("│  Search across blueprint blocks using words related to:                 │")
    print("│                                                                         │")
    print("│    id            Unique block identifier.                      │")
    print("│    name          Simple block name.                            │")
    print("│    domain        Where this block belongs in the system.           │")
    print("│    purpose        What this block is supposed to do.            │")
    print("│    lifecycle  Current block lifecycle.                      │")
    print("│    path          Code path associated with this block.     │")
    print("│    symbol        Related code symbol or block symbol.                   │")
    print("│                                                                         │")
    print("│  Results                                                                │")
    print("│  ───────                                                                │")
    print("│  Search results are displayed as a table.                               │")
    print("│                                                                         │")
    print("│    IDX           Row identifier used to inspect a result.               │")
    print("│    LIFECYCLE  Current block lifecycle.                             │")
    print("│    DOMAIN        Block domain.                                  │")
    print("│    NAME          Block name.                                   │")
    print("│    CODE      Related file path.                                     │")
    print("│                                                                         │")
    print("│  Filters                                                                │")
    print("│  ───────                                                                │")
    print("│  Filters restrict visible search results.                               │")
    print("│                                                                         │")
    print("│    lifecycle  Filter by block lifecycle (status key).              │")
    print("│    domain        Filter by project area.                                │")
    print("│    name          Filter by block name.                         │")
    print("│    path          Filter by file path.                                   │")
    print("│                                                                         │")
    print("│  Examples                                                               │")
    print("│  ────────                                                               │")
    print("│    status=active                                                     │")
    print("│    domain=catalog                                                       │")
    print("│    name=loader                                                          │")
    print("│    path=editor                                                          │")
    print("│                                                                         │")
    print("│  Commands                                                               │")
    print("│  ────────                                                               │")
    print("│  [idx]      Open selected result in Inspector                           │")
    print("│  [/]        Search again                                                │")
    print("│  [f]        Add filter                                                  │")
    print("│  [c]        Clear all filters                                           │")
    print("│  [a]        Show all blocks                                   │")
    print("│  [h]        Toggle help                                                 │")
    print(f"│  {quit_command_label('Quit'):<71}│")
    print("│                                                                         │")
    print("│  Flow                                                                   │")
    print("│  ────                                                                   │")
    print("│  Editor is a search-first launcher for Inspector.                       │")
    print("│                                                                         │")
    print("│  Search → Filter → Select IDX → Inspect → Save → Return to Search       │")
    print("│                                                                         │")
    print("╰─────────────────────────────────────────────────────────────────────────╯")
