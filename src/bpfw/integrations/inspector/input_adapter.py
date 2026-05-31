"""Input adapters for inspector text prompts."""

from collections.abc import Callable

from bpfw.integrations.shared.input_adapter import read_editable_input

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

        return read_editable_input(prompt, self.input_func)
