"""Terminal screen control and input helpers for BPFW Editor."""

import shutil

from bpfw.integrations.shared.visual_boxes import render_box
from bpfw.integrations.shared.visual_width import pad_text


DEFAULT_INPUT_PROMPT = "> "


def clear_screen() -> None:
    """Clear the terminal screen using ANSI escape codes."""

    # Try ANSI escape first (works on most modern terminals)
    print("\033[2J\033[H", end="", flush=True)


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
        return "q"


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


# ---------------------------------------------------------------------------
# Editor search-first UI rendering
# ---------------------------------------------------------------------------

BANNER_TITLE = "Blueprint Framework Editor"


def _editor_block_width(ratio: float = 0.70) -> int:
    """Return a consistent width for editor blocks."""

    terminal_width = get_terminal_width()
    return min(terminal_width, max(72, int(terminal_width * ratio)))


def _results_block_ratio(results: list) -> float:
    """Return dynamic width ratio (70%-95%) based on LOCATION content size."""

    if not results:
        return 0.70

    max_location_length = max(len((record.location or "")) for record in results)
    min_ratio = 0.70
    max_ratio = 0.95
    min_length = 24
    max_length = 120

    if max_location_length <= min_length:
        return min_ratio
    if max_location_length >= max_length:
        return max_ratio

    growth_fraction = (max_location_length - min_length) / (max_length - min_length)
    return min_ratio + (max_ratio - min_ratio) * growth_fraction


def render_editor_banner(ratio: float = 0.70) -> None:
    """Print the editor banner at the top of the screen."""

    banner_width = _editor_block_width(ratio=ratio)
    centered_title = BANNER_TITLE.center(banner_width)
    print("\u2554" + "\u2550" * banner_width + "\u2557")
    print(f"\u2551{pad_text(centered_title, banner_width)}\u2551")
    print("\u255a" + "\u2550" * banner_width + "\u255d")


def render_search_screen() -> None:
    """Render the initial search prompt screen."""

    clear_screen()
    render_editor_banner()
    print()
    print(" Search responsibility to inspect")
    print()
    print(" Search by:")
    print("   id, name, domain, intent, lifecycle, path or symbol")
    print()
    print(" Examples:")
    print("   loader")
    print("   catalog")
    print("   active")
    print("   deprecated")
    print("   blueprint validation")
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
        print(" No responsibilities found.")
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
    # Keep LOCATION narrower so the other columns can breathe.
    location_width = max(18, min(36, total_content_width // 3))
    remaining_width = total_content_width - idx_width - location_width

    # Redistribute remaining width with NAME slightly wider.
    lifecycle_width = max(10, int(remaining_width * 0.28))
    domain_width = max(10, int(remaining_width * 0.28))
    name_width = max(14, remaining_width - lifecycle_width - domain_width)

    # Header
    header = (
        f"\u2502{'IDX':^{idx_width}}"
        f"\u2502{'LIFECYCLE':^{lifecycle_width}}"
        f"\u2502{'DOMAIN':^{domain_width}}"
        f"\u2502{'NAME':^{name_width}}"
        f"\u2502{'LOCATION':^{location_width}}\u2502"
    )
    separator = (
        f"\u251c{'\u2500' * idx_width}"
        f"\u253c{'\u2500' * lifecycle_width}"
        f"\u253c{'\u2500' * domain_width}"
        f"\u253c{'\u2500' * name_width}"
        f"\u253c{'\u2500' * location_width}\u2524"
    )
    top_border = (
        f"\u250c{'\u2500' * idx_width}"
        f"\u252c{'\u2500' * lifecycle_width}"
        f"\u252c{'\u2500' * domain_width}"
        f"\u252c{'\u2500' * name_width}"
        f"\u252c{'\u2500' * location_width}\u2510"
    )
    bottom_border = (
        f"\u2514{'\u2500' * idx_width}"
        f"\u2534{'\u2500' * lifecycle_width}"
        f"\u2534{'\u2500' * domain_width}"
        f"\u2534{'\u2500' * name_width}"
        f"\u2534{'\u2500' * location_width}\u2518"
    )

    print(top_border)
    print(header)
    print(separator)

    for display_index, record in enumerate(results, start=1):
        lifecycle = truncate(record.lifecycle or "-", lifecycle_width).center(lifecycle_width)
        domain = truncate(record.domain or "-", domain_width).center(domain_width)
        name = truncate(record.name or "-", name_width).ljust(name_width)
        location = truncate(record.location or "-", location_width).ljust(location_width)
        index_str = str(display_index).center(idx_width)
        print(f"\u2502{index_str}\u2502{lifecycle}\u2502{domain}\u2502{name}\u2502{location}\u2502")

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
        "[/] search again          [c] clear filters        [q] quit",
        "[a] show all",
    ]
    _render_editor_commands_box(lines, ratio=ratio)


def _render_empty_commands(ratio: float = 0.70) -> None:
    """Render command menu when no results found."""

    lines = [
        "[/] search again          [c] clear filters        [h] help",
        "[a] show all              [q] quit",
    ]
    _render_editor_commands_box(lines, ratio=ratio)


def _render_editor_commands_box(lines: list[str], ratio: float = 0.70) -> None:
    """Render editor commands using inspector-style command box."""

    width = _editor_block_width(ratio=ratio)
    for line in render_box(title="Commands", lines=lines, width=width):
        print(line)


def render_filter_screen() -> None:
    """Render the filter input screen."""

    clear_screen()
    render_editor_banner()
    print()
    print(" Add Filter")
    print()
    print(" Available columns:")
    print("   lifecycle")
    print("   domain")
    print("   name")
    print("   path")
    print()
    print(" Examples:")
    print("   lifecycle=active")
    print("   domain=catalog")
    print("   name=loader")
    print("   path=editor")
    print()


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
    print("   q      quit")


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
    print("│  Search across blueprint responsibilities using words related to:       │")
    print("│                                                                         │")
    print("│    id            Unique responsibility identifier.                      │")
    print("│    name          Simple responsibility name.                            │")
    print("│    domain        Project area related to this responsibility.           │")
    print("│    intent        What this responsibility is supposed to do.            │")
    print("│    lifecycle     Current responsibility status.                         │")
    print("│    path          File location associated with this responsibility.     │")
    print("│    symbol        Related code symbol or snippet name.                   │")
    print("│                                                                         │")
    print("│  Results                                                                │")
    print("│  ───────                                                                │")
    print("│  Search results are displayed as a table.                               │")
    print("│                                                                         │")
    print("│    IDX           Row identifier used to inspect a result.               │")
    print("│    LIFECYCLE     Current snippet status.                                │")
    print("│    DOMAIN        Related project area.                                  │")
    print("│    NAME          Responsibility name.                                   │")
    print("│    LOCATION      Related file path.                                     │")
    print("│                                                                         │")
    print("│  Filters                                                                │")
    print("│  ───────                                                                │")
    print("│  Filters restrict visible search results.                               │")
    print("│                                                                         │")
    print("│    lifecycle     Filter by snippet status.                              │")
    print("│    domain        Filter by project area.                                │")
    print("│    name          Filter by responsibility name.                         │")
    print("│    path          Filter by file path.                                   │")
    print("│                                                                         │")
    print("│  Examples                                                               │")
    print("│  ────────                                                               │")
    print("│    lifecycle=active                                                     │")
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
    print("│  [a]        Show all responsibilities                                   │")
    print("│  [h]        Toggle help                                                 │")
    print("│  [q]        Quit                                                        │")
    print("│                                                                         │")
    print("│  Flow                                                                   │")
    print("│  ────                                                                   │")
    print("│  Editor is a search-first launcher for Inspector.                       │")
    print("│                                                                         │")
    print("│  Search → Filter → Select IDX → Inspect → Save → Return to Search       │")
    print("│                                                                         │")
    print("╰─────────────────────────────────────────────────────────────────────────╯")
