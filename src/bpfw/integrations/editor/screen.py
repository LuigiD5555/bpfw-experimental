"""Terminal screen control and input helpers for BPFW Editor."""

import shutil


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

BANNER_TOP = (
    "\u2554" + "\u2550" * 68 + "\u2557"
)
BANNER_BOTTOM = (
    "\u255a" + "\u2550" * 68 + "\u255d"
)
BANNER_TITLE = "\u2551 Blueprint Framework Editor" + " " * 38 + "\u2551"


def render_editor_banner() -> None:
    """Print the editor banner at the top of the screen."""

    print(BANNER_TOP)
    print(BANNER_TITLE)
    print(BANNER_BOTTOM)


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

    clear_screen()
    render_editor_banner()
    print()
    print(" Search:")
    print(f"   {query or 'all'}")
    print()

    if not results:
        print(" No responsibilities found.")
        print()
        _render_filter_display(filter_display_lines)
        print()
        _render_empty_commands()
        return

    _render_results_table_rows(results)
    print()
    _render_filter_display(filter_display_lines)
    print()
    _render_results_commands()


def _render_results_table_rows(results: list) -> None:
    """Render the actual table of search results."""

    width = get_terminal_width()

    # Column widths: IDX(5) LIFECYCLE(12) DOMAIN(12) NAME(24) LOCATION(rest)
    idx_width = 5
    lifecycle_width = 12
    domain_width = 12
    name_width = 24
    location_width = max(width - idx_width - lifecycle_width - domain_width - name_width - 10, 16)

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


def _render_results_commands() -> None:
    """Render command menu for results screen."""

    print(" Commands:")
    print("   [idx] inspect")
    print("   /      search again")
    print("   f      filter")
    print("   c      clear filters")
    print("   a      show all")
    print("   q      quit")


def _render_empty_commands() -> None:
    """Render command menu when no results found."""

    print(" Commands:")
    print("   /      search again")
    print("   c      clear filters")
    print("   a      show all")
    print("   q      quit")


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
    print("   q      quit")


def render_filter_error(message: str) -> None:
    """Render a filter error message."""

    print()
    print(message)
