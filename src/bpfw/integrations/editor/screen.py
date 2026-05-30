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
NORMAL_RESULT_COLUMNS = ("domain", "name", "purpose")
FILTERED_RESULT_COLUMNS = ("name", "purpose", "location", "codelines")
NORMAL_RESULT_WIDTH_PRIORITY = ("name", "purpose", "domain")
FILTERED_RESULT_WIDTH_PRIORITY = ("location", "name", "purpose", "codelines")
RESULT_COLUMN_LABELS = {
    "domain": "DOMAIN",
    "name": "NAME",
    "purpose": "PURPOSE",
    "location": "LOCATION",
    "codelines": "CODELINES",
}
RESULT_COLUMN_MIN_WIDTHS = {
    "domain": 8,
    "name": 14,
    "purpose": 7,
    "location": 12,
    "codelines": 9,
}
RESULT_COLUMN_MAX_WIDTHS = {
    "domain": 40,
    "name": 72,
    "purpose": 52,
    "location": 56,
    "codelines": 14,
}
ANSI_KEY_REGISTRY = {
    "A": "up",
    "B": "down",
    "C": "right",
    "D": "left",
    "Z": "shift_tab",
}
SINGLE_KEY_REGISTRY = {
    "\r": "enter",
    "\n": "enter",
    " ": "space",
    "\t": "tab",
    "\x7f": "backspace",
    "\x08": "backspace",
}


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
        - 'space' for Space key
        - 'tab' for Tab key
    """
    try:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)

        try:
            tty.setraw(fd)
            character = sys.stdin.read(1)

            if character == "\x1b":
                second_character = sys.stdin.read(1)
                if second_character == "[":
                    third_character = sys.stdin.read(1)
                    return ANSI_KEY_REGISTRY.get(third_character, "")
                if second_character == "\x1b":
                    return ""
                return ""

            mapped_key = SINGLE_KEY_REGISTRY.get(character)
            if mapped_key is not None:
                return mapped_key
            if character == "\x03":
                raise KeyboardInterrupt
            if character == "\x04":
                raise EOFError
            return character.lower()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    except (termios.error, OSError, AttributeError):
        try:
            line = input()
        except EOFError:
            return QUIT_COMMAND
        except KeyboardInterrupt:
            raise
        if not line:
            return "enter"
        first_character = line[0].lower()
        return SINGLE_KEY_REGISTRY.get(first_character, first_character)


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


def _results_block_ratio(results: list, result_columns: tuple[str, ...]) -> float:
    """Return dynamic width ratio (50%-95%) based on required table width."""

    if not results:
        return 0.50

    desired_idx_width = 5
    desired_lifecycle_width = 10
    width_priority = _result_width_priority_for_columns(result_columns)
    desired_column_widths = _desired_result_column_widths(results, result_columns, width_priority)

    separator_width = _result_table_separator_width(result_columns)
    required_content_width = (
        desired_idx_width
        + desired_lifecycle_width
        + sum(desired_column_widths)
    )
    required_block_width = required_content_width + separator_width

    min_ratio = 0.50
    max_ratio = 0.95

    terminal_width = get_terminal_width()
    if terminal_width <= 0:
        return min_ratio

    # _editor_block_width uses: int(terminal_width * ratio) - 2.
    required_ratio = (required_block_width + 2) / terminal_width
    return max(min_ratio, min(max_ratio, required_ratio))


def _max_result_column_value_width(results: list, column: str) -> int:
    """Return the longest display value width for one result column."""

    label_width = len(RESULT_COLUMN_LABELS[column])
    value_width = max((len(_result_column_value(record, column) or "-") for record in results), default=0)
    return max(label_width, value_width)


def _compute_results_column_widths(
    results: list,
    total_content_width: int,
    result_columns: tuple[str, ...],
) -> tuple[int, int, list[int]]:
    """Compute result table widths using explicit width priority."""

    idx_width = 5
    lifecycle_width = 10
    width_priority = _result_width_priority_for_columns(result_columns)

    min_column_widths = [RESULT_COLUMN_MIN_WIDTHS[column] for column in result_columns]

    available_main_width = total_content_width - idx_width - lifecycle_width
    if available_main_width <= sum(min_column_widths):
        return idx_width, lifecycle_width, _shrink_widths_to_available(
            widths=min_column_widths,
            available_width=max(1, available_main_width),
            result_columns=result_columns,
            width_priority=width_priority,
        )

    desired_column_widths = _desired_result_column_widths(results, result_columns, width_priority)
    requested_main_width = sum(desired_column_widths)

    if requested_main_width <= available_main_width:
        extra_width = available_main_width - requested_main_width
        priority_column_index = result_columns.index(width_priority[0])
        desired_column_widths[priority_column_index] += extra_width
        return idx_width, lifecycle_width, desired_column_widths

    overflow = requested_main_width - available_main_width

    for column_index in _shrink_order(result_columns, width_priority):
        reducible_width = desired_column_widths[column_index] - min_column_widths[column_index]
        reduction = min(overflow, reducible_width)
        desired_column_widths[column_index] -= reduction
        overflow -= reduction
        if overflow <= 0:
            break

    return idx_width, lifecycle_width, desired_column_widths


def _desired_result_column_widths(
    results: list,
    result_columns: tuple[str, ...],
    width_priority: tuple[str, ...],
) -> list[int]:
    """Return desired widths with priority columns kept uncapped."""

    desired_widths: list[int] = []
    priority_columns = set(width_priority[:3])
    for column in result_columns:
        value_width = _max_result_column_value_width(results, column)
        if column in priority_columns:
            desired_widths.append(max(RESULT_COLUMN_MIN_WIDTHS[column], value_width))
            continue
        desired_widths.append(
            max(
                RESULT_COLUMN_MIN_WIDTHS[column],
                min(value_width, RESULT_COLUMN_MAX_WIDTHS[column]),
            )
        )
    return desired_widths


def _result_width_priority_for_columns(result_columns: tuple[str, ...]) -> tuple[str, ...]:
    """Return width priority for the current result table profile."""

    if result_columns == FILTERED_RESULT_COLUMNS:
        return FILTERED_RESULT_WIDTH_PRIORITY
    return NORMAL_RESULT_WIDTH_PRIORITY


def _result_table_separator_width(result_columns: tuple[str, ...]) -> int:
    """Return the total vertical separator width for the result table."""

    fixed_column_count = 2
    return fixed_column_count + len(result_columns) + 1


def _shrink_widths_to_available(
    widths: list[int],
    available_width: int,
    result_columns: tuple[str, ...],
    width_priority: tuple[str, ...],
) -> list[int]:
    """Shrink column widths within available space, preserving priority columns longest."""

    fitted_widths = list(widths)
    overflow = sum(fitted_widths) - available_width
    for column_index in _shrink_order(result_columns, width_priority):
        if overflow <= 0:
            break
        reducible_width = fitted_widths[column_index] - 1
        reduction = min(overflow, reducible_width)
        fitted_widths[column_index] -= reduction
        overflow -= reduction
    return fitted_widths


def _shrink_order(result_columns: tuple[str, ...], width_priority: tuple[str, ...]) -> list[int]:
    """Return column indexes from least important to most important."""

    priority_rank = {column: rank for rank, column in enumerate(width_priority)}
    default_rank = len(width_priority)
    return sorted(
        range(len(result_columns)),
        key=lambda column_index: priority_rank.get(result_columns[column_index], default_rank),
        reverse=True,
    )


def _result_columns_for_filters(filter_display_lines: list[str]) -> tuple[str, ...]:
    """Return result table columns for normal or filtered search state."""

    has_active_filters = any(line != "none" for line in filter_display_lines)
    if has_active_filters:
        return FILTERED_RESULT_COLUMNS
    return NORMAL_RESULT_COLUMNS


def _result_column_value(record: object, column: str) -> str:
    """Return a display value for one configured result column."""

    if column == "codelines":
        start_line = getattr(record, "start_line", None)
        end_line = getattr(record, "end_line", None)
        if start_line is None or end_line is None:
            return ""
        return f"{start_line}-{end_line}"

    value = getattr(record, column, "")
    if value is None:
        return ""
    return str(value)


def _format_result_cell(value: str, width: int, preserve_priority: bool) -> str:
    """Format a table cell, avoiding ellipsis for protected priority values."""

    if preserve_priority and len(value) > width:
        return value[:width].ljust(width)
    return truncate(value, width).ljust(width)


def render_editor_banner(ratio: float = 0.70) -> None:
    """Print the editor banner at the top of the screen."""

    banner_width = _editor_block_width(ratio=ratio)
    for line in render_header(title=BANNER_TITLE, width=banner_width, theme=DEFAULT_THEME, centered=True):
        print(line)


def render_search_screen() -> None:
    """Render the initial search prompt screen."""

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
    """Render the search results screen with a table and command menu.

    results: list of SearchRecord
    filter_display_lines: display lines from FilterState
    """

    result_columns = _result_columns_for_filters(filter_display_lines)
    block_ratio = _results_block_ratio(results, result_columns)
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

    _render_results_table_rows(results, ratio=block_ratio, result_columns=result_columns)
    print()
    _render_filter_display(filter_display_lines)
    print()
    _render_results_commands(ratio=block_ratio)


def _render_results_table_rows(
    results: list,
    ratio: float = 0.70,
    result_columns: tuple[str, ...] = NORMAL_RESULT_COLUMNS,
) -> None:
    """Render the actual table of search results."""

    width = _editor_block_width(ratio=ratio)

    total_content_width = max(1, width - _result_table_separator_width(result_columns))
    idx_width, status_width, dynamic_widths = _compute_results_column_widths(
        results,
        total_content_width,
        result_columns,
    )
    width_priority = _result_width_priority_for_columns(result_columns)
    protected_columns = set(width_priority[:3])

    # Header
    header = (
        f"\u2502{'IDX':^{idx_width}}"
        f"\u2502{'LIFECYCLE':^{status_width}}"
        + "".join(
            f"\u2502{truncate(RESULT_COLUMN_LABELS[column], column_width):^{column_width}}"
            for column, column_width in zip(result_columns, dynamic_widths, strict=True)
        )
        + "\u2502"
    )
    separator = (
        f"\u251c{'\u2500' * idx_width}"
        f"\u253c{'\u2500' * status_width}"
        + "".join(f"\u253c{'\u2500' * column_width}" for column_width in dynamic_widths)
        + "\u2524"
    )
    top_border = (
        f"\u250c{'\u2500' * idx_width}"
        f"\u252c{'\u2500' * status_width}"
        + "".join(f"\u252c{'\u2500' * column_width}" for column_width in dynamic_widths)
        + "\u2510"
    )
    bottom_border = (
        f"\u2514{'\u2500' * idx_width}"
        f"\u2534{'\u2500' * status_width}"
        + "".join(f"\u2534{'\u2500' * column_width}" for column_width in dynamic_widths)
        + "\u2518"
    )

    print(top_border)
    print(header)
    print(separator)

    for display_index, record in enumerate(results, start=1):
        status = truncate(record.lifecycle or "-", status_width).center(status_width)
        dynamic_values = [
            _format_result_cell(
                value=_result_column_value(record, column) or "-",
                width=column_width,
                preserve_priority=column in protected_columns,
            )
            for column, column_width in zip(result_columns, dynamic_widths, strict=True)
        ]
        index_str = str(display_index).center(idx_width)
        dynamic_cells = "".join(f"\u2502{value}" for value in dynamic_values)
        print(f"\u2502{index_str}\u2502{status}{dynamic_cells}\u2502")

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
