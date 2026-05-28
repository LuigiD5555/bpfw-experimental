"""PURPOSE input adapters for inspector text prompts
DOMAIN  inspector workflow
"""

import builtins
import sys
from collections.abc import Callable

InputFunc = Callable[[str], str]


class InspectorInputReader:
    """PURPOSE read inspector input with editable terminal support when available
    DOMAIN  inspector workflow
    """

    def __init__(self, input_func: InputFunc) -> None:
        """PURPOSE set up the reader with the input function used by the session
        DOMAIN  inspector workflow
        """

        self.input_func = input_func

    def read(self, prompt: str) -> str:
        """PURPOSE read one line of input using the best available line editor
        DOMAIN  inspector workflow
        """

        if self._should_use_prompt_toolkit():
            return self._read_with_prompt_toolkit(prompt)
        return self.input_func(prompt)

    def _should_use_prompt_toolkit(self) -> bool:
        """PURPOSE check whether prompt_toolkit should handle interactive input
        DOMAIN  inspector workflow
        """

        return (
            self.input_func is builtins.input
            and sys.stdin.isatty()
            and sys.stdout.isatty()
        )

    def _read_with_prompt_toolkit(self, prompt: str) -> str:
        """PURPOSE read input through prompt_toolkit with fallback when unavailable
        DOMAIN  inspector workflow
        """

        try:
            from prompt_toolkit import prompt as read_prompt
        except ImportError:
            return self.input_func(prompt)
        return read_prompt(prompt)
