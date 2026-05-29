"""Shared interactive runtime helpers for terminal integrations."""

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
    """Return the standard command label for command boxes."""

    return f"[{shortcut}] {description}"


def quit_command_label(description: str = "quit") -> str:
    """Return the standard quit command label for command boxes."""

    return command_label(QUIT_COMMAND_KEY, description)


def normalize_command(raw_value: str) -> str:
    """Return normalized command text for dispatch."""

    command = raw_value.strip().lower()
    if command in {QUIT_COMMAND_KEY, "ctrl + c", QUIT_COMMAND, "q"}:
        return QUIT_COMMAND
    return command


def is_back_command(command: str) -> bool:
    """Return True when command is a back navigation action."""

    return command in {"b", "back"}


def is_quit_command(command: str) -> bool:
    """Return True when command is a quit action."""

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
    """Run a generic render/input/dispatch loop for terminal tools."""

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
