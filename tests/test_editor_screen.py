import builtins

from bpfw.integrations.editor import screen


def test_read_input_uses_default_prompt_for_empty_prompt(monkeypatch) -> None:
    prompts = []

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return "  r  "

    monkeypatch.setattr(builtins, "input", fake_input)

    assert screen.read_input("") == "r"
    assert prompts == ["> "]


def test_wait_for_enter_shows_continue_text_then_default_prompt(
    capsys, monkeypatch
) -> None:
    prompts = []

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return ""

    monkeypatch.setattr(builtins, "input", fake_input)

    screen.wait_for_enter()

    assert capsys.readouterr().out == "Press Enter to continue.\n"
    assert prompts == ["> "]
