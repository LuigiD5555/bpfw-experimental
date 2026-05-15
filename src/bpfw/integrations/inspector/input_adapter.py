"""Input adapters for inspector text prompts."""

import builtins
import sys
from collections.abc import Callable

InputFunc = Callable[[str], str]


class InspectorInputReader:
    """Read inspector input with editable terminal support when available.

    The inspector can receive a custom input function in tests or scripted runs.
    In that case the custom function is used exactly as provided. When the
    default interactive input function is used in a real terminal, prompt_toolkit
    is used so arrow keys, Home/End, and normal line editing work correctly.
    """

    def __init__(self, input_func: InputFunc) -> None:
        """Initialize the reader with the input function used by the session.

        Args:
            input_func: Function used to read a line of user input.
        """

        self.input_func = input_func

    def read(self, prompt: str) -> str:
        """Read one line of input using the best available line editor.

        Args:
            prompt: Prompt shown before reading user input.

        Returns:
            The text entered by the user.

        Raises:
            EOFError: If the underlying input mechanism reaches EOF.
            KeyboardInterrupt: If the user interrupts the input operation.
        """

        if self._should_use_prompt_toolkit():
            return self._read_with_prompt_toolkit(prompt)
        return self.input_func(prompt)

    def _should_use_prompt_toolkit(self) -> bool:
        """Return True when prompt_toolkit should handle interactive input."""

        return (
            self.input_func is builtins.input
            and sys.stdin.isatty()
            and sys.stdout.isatty()
        )

    def _read_with_prompt_toolkit(self, prompt: str) -> str:
        """Read input through prompt_toolkit with fallback when unavailable.

        Args:
            prompt: Prompt shown before reading user input.

        Returns:
            The text entered by the user.
        """

        try:
            from prompt_toolkit import prompt as read_prompt
        except ImportError:
            return self.input_func(prompt)
        return read_prompt(prompt)
