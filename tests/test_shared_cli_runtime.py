from bpfw.integrations.shared.cli_runtime import (
    is_back_command,
    is_quit_command,
    normalize_command,
    run_interactive_loop,
)


def test_normalize_command_lowers_and_strips() -> None:
    assert normalize_command("  HeLLo  ") == "hello"


def test_back_and_quit_aliases() -> None:
    assert is_back_command("b")
    assert is_back_command("back")
    assert is_quit_command("q")
    assert is_quit_command("quit")


def test_run_interactive_loop_dispatches_and_stops_on_exit() -> None:
    state = {"screen": "main", "exit": False, "handled": []}
    commands = iter(["a", "q"])

    def render_step() -> None:
        return None

    def read_command(prompt: str) -> str:
        return next(commands)

    def handle_main(command: str) -> None:
        state["handled"].append(command)
        if command == "q":
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
    assert state["handled"] == ["a", "q"]
