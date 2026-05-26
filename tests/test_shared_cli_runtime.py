from bpfw.integrations.shared.cli_runtime import (
    QUIT_COMMAND,
    QUIT_COMMAND_KEY,
    command_label,
    is_back_command,
    is_quit_command,
    normalize_command,
    quit_command_label,
    run_interactive_loop,
)


def test_normalize_command_lowers_and_strips() -> None:
    assert normalize_command("  HeLLo  ") == "hello"
    assert normalize_command(QUIT_COMMAND_KEY) == QUIT_COMMAND
    assert normalize_command("ctrl+c") == QUIT_COMMAND
    assert normalize_command("ctrl + c") == QUIT_COMMAND
    assert normalize_command(QUIT_COMMAND) == QUIT_COMMAND
    assert normalize_command("q") == QUIT_COMMAND


def test_command_labels_use_shared_quit_key() -> None:
    assert command_label("h", "help") == "[h] help"
    assert quit_command_label() == "[ctrl+c] quit"
    assert quit_command_label("Quit without saving") == "[ctrl+c] Quit without saving"


def test_back_and_quit_aliases() -> None:
    assert is_back_command("b")
    assert is_back_command("back")
    assert is_quit_command("q")
    assert is_quit_command(QUIT_COMMAND)
    assert is_quit_command("quit")


def test_run_interactive_loop_dispatches_and_stops_on_exit() -> None:
    state = {"screen": "main", "exit": False, "handled": []}
    commands = iter(["a", "quit"])

    def render_step() -> None:
        return None

    def read_command(prompt: str) -> str:
        return next(commands)

    def handle_main(command: str) -> None:
        state["handled"].append(command)
        if command == "quit":
            state["exit"] = True

    exit_code = run_interactive_loop(
        render_step=render_step,
        read_command=read_command,
        get_screen=lambda: state["screen"],
        resolve_prompt=lambda _screen: "> ",
        handlers_by_screen={"main": handle_main},
        should_exit=lambda: bool(state["exit"]),
    )

    assert exit_code == 0
    assert state["handled"] == ["a", "quit"]
