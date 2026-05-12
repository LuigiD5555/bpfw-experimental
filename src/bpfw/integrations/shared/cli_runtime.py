"""Shared interactive runtime helpers for terminal integrations."""

from collections.abc import Callable


CommandReader = Callable[[str], str]
RenderStep = Callable[[], None]
ScreenGetter = Callable[[], str]
PromptResolver = Callable[[str], str]
ScreenHandler = Callable[[str], None]
ExitChecker = Callable[[], bool]


def normalize_command(raw_value: str) -> str:
    """Return normalized command text for dispatch."""

    return raw_value.strip().lower()


def is_back_command(command: str) -> bool:
    """Return True when command is a back navigation action."""

    return command in {"b", "back"}


def is_quit_command(command: str) -> bool:
    """Return True when command is a quit action."""

    return command in {"q", "quit"}


def run_interactive_loop(
    *,
    render_step: RenderStep,
    read_command: CommandReader,
    get_screen: ScreenGetter,
    resolve_prompt: PromptResolver,
    handlers_by_screen: dict[str, ScreenHandler],
    should_exit: ExitChecker,
) -> int:
    """Run a generic render/input/dispatch loop for CLI integrations."""

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
