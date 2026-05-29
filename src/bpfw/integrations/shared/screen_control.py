"""Shared terminal screen control helpers for interactive integrations."""

import sys


def refresh_screen() -> None:
    """Refresh terminal screen in-place when running on an interactive TTY."""

    if not sys.stdout.isatty():
        return
    # ANSI clear screen + cursor home.
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()

