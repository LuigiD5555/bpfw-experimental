"""Shared editable input helpers for interactive terminal integrations."""

import builtins
import sys
from collections.abc import Callable

InputFunc = Callable[[str], str]


def read_editable_input(prompt: str, input_func: InputFunc | None = None) -> str:
    """Read one editable terminal line when the terminal supports it.

    Args:
        prompt: Prompt shown before reading user input.
        input_func: Optional input function used by tests or scripted sessions.

    Returns:
        The line entered by the user.

    Raises:
        EOFError: If the input stream is closed.
        KeyboardInterrupt: If the user interrupts input.
    """

    resolved_input_func = input_func or builtins.input
    if should_use_editable_input(resolved_input_func):
        return _read_with_prompt_toolkit(prompt, resolved_input_func)
    return resolved_input_func(prompt)


def should_use_editable_input(input_func: InputFunc) -> bool:
    """Return True when prompt_toolkit should handle interactive input.

    Args:
        input_func: Input function requested by the caller.

    Returns:
        True when the default input function is used in an interactive TTY.
    """

    return (
        input_func is builtins.input
        and sys.stdin.isatty()
        and sys.stdout.isatty()
    )


def _read_with_prompt_toolkit(prompt: str, fallback_input_func: InputFunc) -> str:
    """Read input with prompt_toolkit and fall back to plain input.

    Args:
        prompt: Prompt shown before reading user input.
        fallback_input_func: Input function used when prompt_toolkit is unavailable.

    Returns:
        The line entered by the user.
    """

    try:
        from prompt_toolkit import prompt as read_prompt
    except ImportError:
        return fallback_input_func(prompt)
    return read_prompt(prompt)
