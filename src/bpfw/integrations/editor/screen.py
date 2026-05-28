"""PURPOSE terminal screen control and input helpers for BPFW Editor
DOMAIN  editor workflow
"""

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


def get_terminal_width() -> int:
    """PURPOSE get terminal width with a safe minimum
    DOMAIN  editor workflow
    """

    try:
        return shutil.get_terminal_size((80, 24)).columns
    except (ValueError, OSError):
        return 80


def get_terminal_height() -> int:
    """PURPOSE get terminal height with a safe minimum
    DOMAIN  editor workflow
    """

    try:
        return shutil.get_terminal_size((80, 24)).lines
    except (ValueError, OSError):
        return 24


def _normalize_prompt(prompt: str) -> str:
    """PURPOSE get the visible editor prompt for input-ready states
    DOMAIN  editor workflow
    """

    return prompt or DEFAULT_INPUT_PROMPT


def read_input(prompt: str = DEFAULT_INPUT_PROMPT) -> str:
    """PURPOSE read a line of input, returning stripped value
    DOMAIN  editor workflow
    """

    try:
        value = input(_normalize_prompt(prompt))
        return value.strip()
    except (EOFError, KeyboardInterrupt):
        return QUIT_COMMAND


def read_line(prompt: str = DEFAULT_INPUT_PROMPT) -> str:
    """PURPOSE read a single line of input with a prompt
    DOMAIN  editor workflow
    """

    try:
        value = input(_normalize_prompt(prompt))
        return value.rstrip("\n")
    except (EOFError, KeyboardInterrupt):
        return ""


def wait_for_enter() -> None:
    """PURPOSE wait for the user to press Enter
    DOMAIN  editor workflow
    """

    try:
        print("Press Enter to continue.")
        input(DEFAULT_INPUT_PROMPT)
    except (EOFError, KeyboardInterrupt):
        pass


def paginate_items(items: list, page: int, page_size: int = 20) -> tuple[list, int, int, int]:
    """PURPOSE get a page of items and pagination metadata
    DOMAIN  editor workflow
    """

    total = len(items)
    start = (page - 1) * page_size
    end = min(start + page_size, total)

    if start >= total:
        return [], 0, 0, total

    return items[start:end], start + 1, end, total


def format_paging_footer(start: int, end: int, total: int) -> str:
    """PURPOSE format a pagination status line
    DOMAIN  editor workflow
    """

    if total == 0:
        return "Showing 0 items"
    return f"Showing {start}-{end} of {total}"


def truncate(text: str, max_width: int) -> str:
    """PURPOSE truncate text to fit within max_width, adding ellipsis if needed
    DOMAIN  editor workflow
    """

    if len(text) <= max_width:
        return text
    if max_width < 4:
        return text[:max_width]
    return text[: max_width - 3] + "..."


def read_multiline() -> list[str]:
    """PURPOSE read multiple lines until an empty line is entered
    DOMAIN  editor workflow
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
    """PURPOSE read a single keystroke from stdin
    DOMAIN  editor workflow
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
            if ch == '\x1b':  # ANSI sequence
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
                elif ch2 == '\x1b':
                    return ''
                return ''
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
    """PURPOSE get a consistent width for editor blocks
    DOMAIN  editor workflow
    """

    terminal_width = get_terminal_width()
    preferred_width = max(20, int(terminal_width * ratio) - 2)
    minimum_width = max(20, int(terminal_width * DEFAULT_THEME.min_ratio) - 2)
    maximum_width = max(minimum_width, int(terminal_width * DEFAULT_THEME.max_ratio) - 2)
    return max(minimum_width, min(maximum_width, preferred_width))


def _results_block_ratio(results: list) -> float:
    """PURPOSE get dynamic width ratio (50%-95%) based on required table width
    DOMAIN  editor workflow
    """

    if not results:
        return 0.50

    max_name_length = max(len((record.name or "-")) for record in results)
    max_domain_length = max(len((record.domain or "-")) for record in results)
    max_purpose_length = max(len((record.purpose or "-")) for record in results)

    desired_idx_width = 5
    desired_lifecycle_width = 10
    desired_domain_width = max(10, min(max_domain_length, 40))
    desired_name_width = max(14, min(max_name_length, 72))
    desired_purpose_width = max(8, min(max_purpose_length, 52))

    # Five columns use six vertical separators in the table renderer.
    required_content_width = (
        desired_idx_width
        + desired_lifecycle_width
        + desired_domain_width
        + desired_name_width
        + desired_purpose_width
    )
    required_block_width = required_content_width + 6

    min_ratio = 0.50
    max_ratio = 0.95

    terminal_width = get_terminal_width()
    if terminal_width <= 0:
        return min_ratio

    # _editor_block_width uses: int(terminal_width * ratio) - 2.
    required_ratio = (required_block_width + 2) / terminal_width
    return max(min_ratio, min(max_ratio, required_ratio))


def _compute_results_column_widths(results: list, total_content_width: int) -> tuple[int, int, int, int, int]:
    """PURPOSE calculate IDX/LIFECYCLE/DOMAIN/NAME/PURPOSE widths with truncation priority
    DOMAIN  editor workflow
    """

    idx_width = 5
    lifecycle_width = 10

    max_domain_length = max((len(record.domain or "-") for record in results), default=6)
    max_name_length = max((len(record.name or "-") for record in results), default=4)
    max_purpose_length = max((len(record.purpose or "-") for record in results), default=7)

    min_domain_width = 10
    min_name_width = 14
    min_purpose_width = 8

    available_main_width = total_content_width - idx_width - lifecycle_width
    if available_main_width <= (min_domain_width + min_name_width + min_purpose_width):
        return idx_width, lifecycle_width, min_domain_width, min_name_width, min_purpose_width

    desired_domain_width = max(min_domain_width, min(max_domain_length, 40))
    desired_name_width = max(min_name_width, min(max_name_length, 72))
    desired_purpose_width = max(min_purpose_width, min(max_purpose_length, 52))
    requested_main_width = desired_domain_width + desired_name_width + desired_purpose_width

    if requested_main_width <= available_main_width:
        extra_width = available_main_width - requested_main_width
        desired_name_width += extra_width
        return idx_width, lifecycle_width, desired_domain_width, desired_name_width, desired_purpose_width

    overflow = requested_main_width - available_main_width

    reducible_purpose = desired_purpose_width - min_purpose_width
    reduce_purpose = min(overflow, reducible_purpose)
    desired_purpose_width -= reduce_purpose
    overflow -= reduce_purpose

    reducible_domain = desired_domain_width - min_domain_width
    reduce_domain = min(overflow, reducible_domain)
    desired_domain_width -= reduce_domain
    overflow -= reduce_domain

    reducible_name = desired_name_width - min_name_width
    reduce_name = min(overflow, reducible_name)
    desired_name_width -= reduce_name

    return idx_width, lifecycle_width, desired_domain_width, desired_name_width, desired_purpose_width


def render_editor_banner(ratio: float = 0.70) -> None:
    """PURPOSE print the editor banner at the top of the screen
    DOMAIN  editor workflow
    """

    banner_width = _editor_block_width(ratio=ratio)
    for line in render_header(title=BANNER_TITLE, width=banner_width, theme=DEFAULT_THEME, centered=True):
        print(line)


def render_search_screen() -> None:
    """PURPOSE show the initial search prompt screen
    DOMAIN  editor workflow
    """

    refresh_screen()
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
    """PURPOSE show the search results screen with a table and command menu
    DOMAIN  editor workflow
    """

    block_ratio = _results_block_ratio(results)
    refresh_screen()
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
    for display_index, record in enumerate(results, start=1):
        if record.location:
            print(f" [{display_index}] location: {record.location}")
    print()
    _render_filter_display(filter_display_lines)
    print()
    _render_results_commands(ratio=block_ratio)


def _render_results_table_rows(results: list, ratio: float = 0.70) -> None:
    """PURPOSE show the actual table of search results
    DOMAIN  editor workflow
    """

    width = _editor_block_width(ratio=ratio)

    # Five columns need six vertical separators.
    total_content_width = max(54, width - 6)
    idx_width, status_width, domain_width, name_width, purpose_width = _compute_results_column_widths(
        results,
        total_content_width,
    )

    # Header
    header = (
        f"\u2502{'IDX':^{idx_width}}"
        f"\u2502{'LIFECYCLE':^{status_width}}"
        f"\u2502{'DOMAIN':^{domain_width}}"
        f"\u2502{'NAME':^{name_width}}"
        f"\u2502{'PURPOSE':^{purpose_width}}\u2502"
    )
    separator = (
        f"\u251c{'\u2500' * idx_width}"
        f"\u253c{'\u2500' * status_width}"
        f"\u253c{'\u2500' * domain_width}"
        f"\u253c{'\u2500' * name_width}"
        f"\u253c{'\u2500' * purpose_width}\u2524"
    )
    top_border = (
        f"\u250c{'\u2500' * idx_width}"
        f"\u252c{'\u2500' * status_width}"
        f"\u252c{'\u2500' * domain_width}"
        f"\u252c{'\u2500' * name_width}"
        f"\u252c{'\u2500' * purpose_width}\u2510"
    )
    bottom_border = (
        f"\u2514{'\u2500' * idx_width}"
        f"\u2534{'\u2500' * status_width}"
        f"\u2534{'\u2500' * domain_width}"
        f"\u2534{'\u2500' * name_width}"
        f"\u2534{'\u2500' * purpose_width}\u2518"
    )

    print(top_border)
    print(header)
    print(separator)

    for display_index, record in enumerate(results, start=1):
        status = truncate(record.status or "-", status_width).center(status_width)
        domain = truncate(record.domain or "-", domain_width).center(domain_width)
        name = truncate(record.name or "-", name_width).ljust(name_width)
        purpose_value = record.purpose or "-"
        if record.location:
            purpose_value = f"{purpose_value} [{record.location}]"
        purpose = truncate(purpose_value, purpose_width).ljust(purpose_width)
        index_str = str(display_index).center(idx_width)
        print(f"\u2502{index_str}\u2502{status}\u2502{domain}\u2502{name}\u2502{purpose}\u2502")

    print(bottom_border)


def _render_filter_display(filter_display_lines: list[str]) -> None:
    """PURPOSE show active filters section
    DOMAIN  editor workflow
    """

    print(" Active filters:")
    for line in filter_display_lines:
        print(f"   {line}")


def _render_results_commands(ratio: float = 0.70) -> None:
    """PURPOSE show command menu for results screen
    DOMAIN  editor workflow
    """

    lines = [
        "[idx] inspect             [f] filter               [h] help",
        f"[/] search again          [c] clear filters        {quit_command_label()}",
        "[a] show all",
    ]
    _render_editor_commands_box(lines, ratio=ratio)


def _render_empty_commands(ratio: float = 0.70) -> None:
    """PURPOSE show command menu when no results found
    DOMAIN  editor workflow
    """

    lines = [
        "[/] search again          [c] clear filters        [h] help",
        f"[a] show all              {quit_command_label()}",
    ]
    _render_editor_commands_box(lines, ratio=ratio)


def _render_editor_commands_box(lines: list[str], ratio: float = 0.70) -> None:
    """PURPOSE show editor commands using inspector-style command box
    DOMAIN  editor workflow
    """

    width = _editor_block_width(ratio=ratio)
    for line in render_commands_box(lines=lines, width=width, theme=DEFAULT_THEME, wrap_mode="safe_wrap"):
        print(line)


def render_filter_screen() -> None:
    """PURPOSE show the filter input screen
    DOMAIN  editor workflow
    """

    refresh_screen()
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
    """PURPOSE show examples in a boxed multiline section
    DOMAIN  editor workflow
    """

    width = compute_panel_width(
        content_lines=example_lines,
        title="Examples",
        terminal_width=get_terminal_width(),
        theme=DEFAULT_THEME,
    )
    for line in render_box(title="Examples", lines=example_lines, width=width):
        print(line)


def _render_search_scope_box(title: str, lines: list[str], ratio: float = 0.70) -> None:
    """PURPOSE show search scope details in a boxed section
    DOMAIN  editor workflow
    """

    width = compute_panel_width(
        content_lines=lines,
        title=title,
        terminal_width=get_terminal_width(),
        theme=DEFAULT_THEME,
    )
    for line in render_box(title=title, lines=lines, width=width):
        print(line)


def render_invalid_selection() -> None:
    """PURPOSE show invalid IDX selection message
    DOMAIN  editor workflow
    """

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
    """PURPOSE show a filter error message
    DOMAIN  editor workflow
    """

    print()
    print(message)


def render_editor_help_screen() -> None:
    """PURPOSE show the editor help screen
    DOMAIN  editor workflow
    """

    refresh_screen()
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
    print("│    PURPOSE       Why the block exists.                                 │")
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
