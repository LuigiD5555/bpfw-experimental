from pathlib import Path

from bpfw.integrations.inspect_base import (
    apply_automatic_authority_fields,
    get_incomplete_responsibilities,
    suggest_owner_layer,
)
from bpfw.integrations import wizard as wizard_adapter
from bpfw.integrations.inspect_base import load_inspect_session
from bpfw.integrations.inspect_text import render_text_screen, run_text_inspect_session
from bpfw.integrations.wizard_router import WizardRoute


def _responsibility(
    responsibility_id: str,
    intent: str,
    lifecycle: str,
    path: str = "src/bpfw/catalog/example.py",
    symbol: str = "ExampleService",
) -> dict:
    return {
        "id": responsibility_id,
        "intent": intent,
        "canonical_name": symbol,
        "owner_layer": None,
        "lifecycle": lifecycle,
        "location": {
            "path": path,
            "symbol": symbol,
            "symbol_type": "class",
            "start_line": 2,
            "end_line": 4,
        },
        "duplicate_policy": {
            "group": None,
            "allow_multiple_non_active": True,
            "forbidden_active_duplicates": True,
            "suspected_duplicates": [],
        },
        "related_code": [],
        "replacement": {
            "replaces": None,
            "replaced_by": None,
            "reason": None,
        },
    }


def test_suggest_owner_layer_from_source_package_path() -> None:
    responsibility = _responsibility(
        responsibility_id="example",
        intent="maintain example",
        lifecycle="active",
        path="src/bpfw/protection/authority.py",
    )

    assert suggest_owner_layer(responsibility) == "protection"


def test_get_incomplete_responsibilities_detects_missing_fields() -> None:
    complete = _responsibility("example", "maintain example", "active")
    incomplete = _responsibility("missing", "maintain example", "active")
    incomplete["owner_layer"] = ""
    blueprint_data = {"responsibilities": [complete, incomplete]}

    assert get_incomplete_responsibilities(blueprint_data) == [incomplete]


def test_apply_automatic_authority_fields_derives_groups() -> None:
    active_one = _responsibility("user_creation", "create user", "active")
    active_two = _responsibility(
        "account_registration",
        "create user",
        "active",
        path="src/bpfw/catalog/accounts.py",
        symbol="AccountRegistration",
    )
    blueprint_data = {"responsibilities": [active_one, active_two]}

    apply_automatic_authority_fields(blueprint_data)

    assert active_one["duplicate_policy"]["group"] == "create_user"
    assert active_two["duplicate_policy"]["group"] == "create_user"
    assert active_one["duplicate_policy"]["suspected_duplicates"] == [
        "account_registration"
    ]


def test_text_inspect_renders_expected_sections(tmp_path: Path) -> None:
    responsibility = _responsibility(
        responsibility_id="example",
        intent="",
        lifecycle="active",
        path="src/bpfw/catalog/example.py",
    )
    output: list[str] = []

    render_text_screen(
        project_root=tmp_path,
        responsibility=responsibility,
        index=11,
        total=82,
        print_func=output.append,
    )

    rendered = "\n".join(output)
    assert "BPFW Inspect  12/82  draft" in rendered
    assert "src/bpfw/catalog/example.py :: ExampleService" in rendered
    assert "Code" in rendered
    assert "Authority" in rendered
    assert "Suggestions" in rendered
    assert "[i] intent" in rendered


def test_text_inspect_edits_fields_and_accepts(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text(
        "version: 1\n"
        "responsibilities:\n"
        "  - id: example\n"
        "    canonical_name: ExampleService\n"
        "    owner_layer: ''\n"
        "    lifecycle: ''\n"
        "    intent: ''\n"
        "    notes: ''\n"
        "    location:\n"
        "      path: src/bpfw/catalog/example.py\n"
        "      symbol: ExampleService\n"
        "      symbol_type: class\n"
        "      start_line: 1\n"
        "      end_line: 1\n",
        encoding="utf-8",
    )
    session = load_inspect_session(project_root=tmp_path)
    answers = iter(
        [
            "i",
            "maintain example",
            "o",
            "catalog",
            "l",
            "experimental",
            "n",
            "reviewed",
            "a",
        ]
    )
    output: list[str] = []

    exit_code = run_text_inspect_session(
        session=session,
        input_func=lambda _prompt: next(answers),
        print_func=output.append,
    )

    saved = blueprint_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "maintain example" in saved
    assert "experimental" in saved
    assert "reviewed" in saved


def test_text_inspect_accept_blocks_missing_required_fields(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text(
        "version: 1\n"
        "responsibilities:\n"
        "  - id: example\n"
        "    canonical_name: ''\n"
        "    owner_layer: catalog\n"
        "    lifecycle: active\n"
        "    intent: maintain example\n",
        encoding="utf-8",
    )
    session = load_inspect_session(project_root=tmp_path)
    answers = iter(["a", "q"])
    output: list[str] = []

    exit_code = run_text_inspect_session(
        session=session,
        input_func=lambda _prompt: next(answers),
        print_func=output.append,
    )

    assert exit_code == 0
    assert any("Missing required fields: canonical_name" in line for line in output)


def test_text_inspect_blocks_when_input_is_unavailable(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text(
        "version: 1\n"
        "responsibilities:\n"
        "  - id: example\n"
        "    canonical_name: ExampleService\n"
        "    lifecycle: ''\n"
        "    intent: ''\n",
        encoding="utf-8",
    )
    session = load_inspect_session(project_root=tmp_path)
    output: list[str] = []

    def unavailable_input(_prompt: str) -> str:
        raise EOFError

    exit_code = run_text_inspect_session(
        session=session,
        input_func=unavailable_input,
        print_func=output.append,
    )

    saved = blueprint_path.read_text(encoding="utf-8")
    assert exit_code == 1
    assert "Interactive inspect input unavailable." in output
    assert "exampleservice:example" not in saved


def test_wizard_reports_selected_route_without_interactive_terminal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    route = WizardRoute(
        route_name="inspect",
        authority_state="draft",
        discovered_count=1,
        message="Existing code detected. Routing to inspect.",
    )

    monkeypatch.setattr(wizard_adapter, "select_wizard_route", lambda project_root: route)
    monkeypatch.setattr(wizard_adapter, "can_use_interactive_terminal", lambda: False)

    assert wizard_adapter.run_wizard(tmp_path) == 1
