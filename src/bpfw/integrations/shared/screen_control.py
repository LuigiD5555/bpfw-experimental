"""PURPOSE shared terminal screen control helpers for interactive tools
DOMAIN  terminal UI
"""

import sys


def refresh_screen() -> None:
    """PURPOSE refresh terminal screen in-place when running on an interactive TTY
    DOMAIN  terminal UI
    """

    if not sys.stdout.isatty():
        return
    # ANSI clear screen + cursor home.
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()

