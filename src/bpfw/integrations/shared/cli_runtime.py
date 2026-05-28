"""PURPOSE shared interactive runtime helpers for terminal tools
DOMAIN  terminal UI
"""

from collections.abc import Callable


CommandReader = Callable[[str], str]
RenderStep = Callable[[], None]
ScreenGetter = Callable[[], str]
PromptResolver = Callable[[str], str]
ScreenHandler = Callable[[str], None]
ExitChecker = Callable[[], bool]

QUIT_COMMAND_KEY = "ctrl+c"
QUIT_COMMAND = "quit"
QUIT_COMMAND_ALIASES = frozenset({QUIT_COMMAND, QUIT_COMMAND_KEY, "ctrl + c", "q"})


def command_label(shortcut: str, description: str) -> str:
    """PURPOSE get the standard command label for command boxes
    DOMAIN  terminal UI
    """

    return f"[{shortcut}] {description}"


def quit_command_label(description: str = "quit") -> str:
    """PURPOSE get the standard quit command label for command boxes
    DOMAIN  terminal UI
    """

    return command_label(QUIT_COMMAND_KEY, description)


def normalize_command(raw_value: str) -> str:
    """PURPOSE get clean command text for dispatch
    DOMAIN  terminal UI
    """

    command = raw_value.strip().lower()
    if command in {QUIT_COMMAND_KEY, "ctrl + c", QUIT_COMMAND, "q"}:
        return QUIT_COMMAND
    return command


def is_back_command(command: str) -> bool:
    """PURPOSE check whether command is a back navigation action
    DOMAIN  terminal UI
    """

    return command in {"b", "back"}


def is_quit_command(command: str) -> bool:
    """PURPOSE check whether command is a quit action
    DOMAIN  terminal UI
    """

    return command in QUIT_COMMAND_ALIASES


def run_interactive_loop(
    *,
    render_step: RenderStep,
    read_command: CommandReader,
    get_screen: ScreenGetter,
    resolve_prompt: PromptResolver,
    handlers_by_screen: dict[str, ScreenHandler],
    should_exit: ExitChecker,
) -> int:
    """PURPOSE run a generic render/input/dispatch loop for terminal command tools
    DOMAIN  terminal UI
    """

    try:
        while True:
            render_step()
            current_screen = get_screen()
            prompt = resolve_prompt(current_screen)
            raw_command = read_command(prompt)
            command = normalize_command(raw_command)
            handler = handlers_by_screen.get(current_screen)
            if handler is not None:
                handler(command)
            if should_exit():
                return 0
    except KeyboardInterrupt:
        return 0
    except EOFError:
        return 0
