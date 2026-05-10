"""Tests for the catalog inspector module."""
from pathlib import Path

from bpfw.catalog.intent_suggestions import suggest_intents
from bpfw.integrations.inspector.base import (
    apply_automatic_authority_fields,
    build_code_lines,
    get_incomplete_responsibilities,
    suggest_domain,
    suggest_domains,
)
from bpfw.integrations.inspector.base import load_inspect_session
from bpfw.integrations.inspector.text import (
    render_text_inspector_screen,
    run_text_inspector,
    run_text_inspector_session,
)


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
        "name": symbol,
        "domain": None,
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


def test_suggest_domain_from_source_package_path() -> None:
    responsibility = _responsibility(
        responsibility_id="example",
        intent="maintain example",
        lifecycle="active",
        path="src/bpfw/protection/authority.py",
    )

    assert suggest_domain(responsibility) == "protection"


def test_suggest_domains_returns_list() -> None:
    responsibility = _responsibility(
        responsibility_id="example",
        intent="maintain example",
        lifecycle="active",
        path="src/bpfw/protection/authority.py",
    )

    domains = suggest_domains(responsibility)
    assert isinstance(domains, list)
    assert "protection" in domains


def test_suggest_domains_strips_python_extension() -> None:
    responsibility = _responsibility(
        responsibility_id="intent_suggestions",
        intent="suggest intents",
        lifecycle="active",
        path="src/bpfw/catalog/intent_suggestions.py",
        symbol="IntentSuggestion",
    )

    suggestions = suggest_domains(responsibility)
    assert "intent_suggestions.py" not in suggestions
    assert "intent_suggestions" in suggestions
    assert suggestions[0] == "catalog"


def test_suggest_domains_ignores_package_roots() -> None:
    responsibility = _responsibility(
        responsibility_id="intent_suggestions",
        intent="suggest intents",
        lifecycle="active",
        path="src/bpfw/catalog/intent_suggestions.py",
        symbol="IntentSuggestion",
    )

    suggestions = suggest_domains(responsibility)
    assert "src" not in suggestions
    assert "bpfw" not in suggestions


def test_suggest_domain_returns_first_domain_suggestion() -> None:
    responsibility = _responsibility(
        responsibility_id="intent_suggestions",
        intent="suggest intents",
        lifecycle="active",
        path="src/bpfw/catalog/intent_suggestions.py",
        symbol="IntentSuggestion",
    )

    assert suggest_domain(responsibility) == suggest_domains(responsibility)[0]


def test_suggest_domains_uses_symbol_tokens() -> None:
    responsibility = _responsibility(
        responsibility_id="intent_suggestion",
        intent="suggest intents",
        lifecycle="active",
        path="src/bpfw/catalog/intent_suggestions.py",
        symbol="IntentSuggestion",
    )

    suggestions = suggest_domains(responsibility)
    assert "intent" in suggestions


def test_suggest_domains_prioritizes_inspector_over_integrations() -> None:
    responsibility = _responsibility(
        responsibility_id="inspector_session",
        intent="run inspector",
        lifecycle="active",
        path="src/bpfw/integrations/inspector_text.py",
        symbol="run_text_inspector_session",
    )
    responsibility["location"]["module"] = "bpfw.integrations.inspector_text"

    suggestions = suggest_domains(responsibility)
    assert suggestions[0] == "inspector"


def test_get_incomplete_responsibilities_detects_missing_fields() -> None:
    complete = _responsibility("example", "maintain example", "active")
    complete["domain"] = "example"
    incomplete = _responsibility("missing", "maintain example", "active")
    incomplete["domain"] = ""
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


def test_text_inspector_renders_expected_sections(tmp_path: Path) -> None:
    responsibility = _responsibility(
        responsibility_id="example",
        intent="",
        lifecycle="active",
        path="src/bpfw/catalog/example.py",
    )
    responsibility["detected"] = {
        "methods": ["ExampleService.run"],
        "functions": ["ExampleService.Helper"],
    }
    output: list[str] = []
    intent_suggestions = suggest_intents(responsibility)
    domain_suggestions = suggest_domains(responsibility)

    render_text_inspector_screen(
        project_root=tmp_path,
        issue_type="draft",
        responsibility=responsibility,
        index=11,
        total=82,
        intent_suggestions=intent_suggestions,
        domain_suggestions=domain_suggestions,
        print_func=output.append,
    )

    rendered = "\n".join(output)
    assert "Blueprint Framework Inspector" in rendered
    assert "Authority" in rendered
    assert "Intent suggestions" in rendered
    assert "[6] write custom intent" in rendered
    assert "Domain suggestions" in rendered
    assert " [a] " in rendered
    assert " [s] " in rendered
    assert " [d] " in rendered
    assert " [f] " in rendered
    assert "[g] write custom domain" in rendered
    assert "[z] active" in rendered
    assert "[x] experimental" in rendered
    assert "[c] legacy" in rendered
    assert "[v] deprecated" in rendered
    assert "[Enter] save + next" in rendered
    assert "s save" not in rendered
    assert "l1" not in rendered
    assert "d1" not in rendered


def test_code_preview_includes_blank_lines_after_snippet(tmp_path: Path) -> None:
    source_path = tmp_path / "src" / "bpfw" / "catalog"
    source_path.mkdir(parents=True)
    (source_path / "security.py").write_text(
        "def looks_like_absolute_path(value: str) -> bool:\n"
        "    stripped_value = value.strip()\n"
        "    return stripped_value.startswith('/')\n"
        "\n"
        "\n"
        "def is_allowed_security_policy_path(path: str) -> bool:\n"
        "    return path.startswith('blueprint.policy.security')\n",
        encoding="utf-8",
    )
    responsibility = _responsibility(
        responsibility_id="looks_like_absolute_path",
        intent="absolute_path_checker",
        lifecycle="active",
        path="src/bpfw/catalog/security.py",
        symbol="looks_like_absolute_path",
    )
    responsibility["location"]["symbol_type"] = "function"
    responsibility["location"]["start_line"] = 1
    responsibility["location"]["end_line"] = 3

    rendered = "\n".join(
        build_code_lines(
            project_root=tmp_path,
            responsibility=responsibility,
        )
    )

    assert "  3      return stripped_value.startswith('/')" in rendered
    assert "  4  " in rendered
    assert "  5  " in rendered
    assert "is_allowed_security_policy_path" not in rendered


def test_code_preview_includes_blank_lines_before_snippet(tmp_path: Path) -> None:
    source_path = tmp_path / "src" / "bpfw" / "catalog"
    source_path.mkdir(parents=True)
    (source_path / "security.py").write_text(
        "ABSOLUTE_PATH_POLICY = 'blocked'\n"
        "\n"
        "\n"
        "def looks_like_absolute_path(value: str) -> bool:\n"
        "    return value.startswith('/')\n",
        encoding="utf-8",
    )
    responsibility = _responsibility(
        responsibility_id="looks_like_absolute_path",
        intent="absolute_path_checker",
        lifecycle="active",
        path="src/bpfw/catalog/security.py",
        symbol="looks_like_absolute_path",
    )
    responsibility["location"]["symbol_type"] = "function"
    responsibility["location"]["start_line"] = 4
    responsibility["location"]["end_line"] = 5

    rendered = "\n".join(
        build_code_lines(
            project_root=tmp_path,
            responsibility=responsibility,
        )
    )

    assert "  1  ABSOLUTE_PATH_POLICY" not in rendered
    assert "  2  " in rendered
    assert "  3  " in rendered
    assert "  4  def looks_like_absolute_path" in rendered


def test_code_preview_does_not_cross_into_next_top_level_snippet(tmp_path: Path) -> None:
    source_path = tmp_path / "src" / "bpfw" / "catalog"
    source_path.mkdir(parents=True)
    (source_path / "security.py").write_text(
        "def looks_like_absolute_path(value: str) -> bool:\n"
        "    stripped_value = value.strip()\n"
        "    return stripped_value.startswith('/')\n"
        "\n"
        "\n"
        "def is_allowed_security_policy_path(path: str) -> bool:\n"
        "    return path.startswith('blueprint.policy.security')\n",
        encoding="utf-8",
    )
    responsibility = _responsibility(
        responsibility_id="looks_like_absolute_path",
        intent="absolute_path_checker",
        lifecycle="active",
        path="src/bpfw/catalog/security.py",
        symbol="looks_like_absolute_path",
    )
    responsibility["location"]["symbol_type"] = "function"
    responsibility["location"]["start_line"] = 1
    responsibility["location"]["end_line"] = 3

    rendered = "\n".join(
        build_code_lines(
            project_root=tmp_path,
            responsibility=responsibility,
        )
    )

    assert "looks_like_absolute_path" in rendered
    assert "is_allowed_security_policy_path" not in rendered


def test_code_preview_stops_at_next_same_indent_code(tmp_path: Path) -> None:
    source_path = tmp_path / "src" / "bpfw" / "catalog"
    source_path.mkdir(parents=True)
    (source_path / "security.py").write_text(
        "def looks_like_absolute_path(value: str) -> bool:\n"
        "    stripped_value = value.strip()\n"
        "    return stripped_value.startswith('/')\n"
        "\n"
        "\n"
        "ABSOLUTE_PATH_POLICY = 'blocked'\n",
        encoding="utf-8",
    )
    responsibility = _responsibility(
        responsibility_id="looks_like_absolute_path",
        intent="absolute_path_checker",
        lifecycle="active",
        path="src/bpfw/catalog/security.py",
        symbol="looks_like_absolute_path",
    )
    responsibility["location"]["symbol_type"] = "function"
    responsibility["location"]["start_line"] = 1
    responsibility["location"]["end_line"] = 3

    rendered = "\n".join(
        build_code_lines(
            project_root=tmp_path,
            responsibility=responsibility,
        )
    )

    assert "looks_like_absolute_path" in rendered
    assert "ABSOLUTE_PATH_POLICY" not in rendered


def test_code_preview_includes_class_decorator_lines(tmp_path: Path) -> None:
    source_path = tmp_path / "src" / "bpfw" / "catalog"
    source_path.mkdir(parents=True)
    (source_path / "domain_suggestions.py").write_text(
        "from dataclasses import dataclass\n"
        "\n"
        "@dataclass(frozen=True, slots=True)\n"
        "class DomainSuggestion:\n"
        "    text: str\n",
        encoding="utf-8",
    )
    responsibility = _responsibility(
        responsibility_id="domain_suggestion",
        intent="suggest domain",
        lifecycle="active",
        path="src/bpfw/catalog/domain_suggestions.py",
        symbol="DomainSuggestion",
    )
    responsibility["location"]["symbol_type"] = "class"
    responsibility["location"]["start_line"] = 4
    responsibility["location"]["end_line"] = 5

    rendered = "\n".join(
        build_code_lines(
            project_root=tmp_path,
            responsibility=responsibility,
        )
    )

    assert "  3  @dataclass(frozen=True, slots=True)" in rendered
    assert "  4  class DomainSuggestion:" in rendered


def test_code_preview_includes_function_decorator_lines(tmp_path: Path) -> None:
    source_path = tmp_path / "src" / "bpfw" / "catalog"
    source_path.mkdir(parents=True)
    (source_path / "helpers.py").write_text(
        "def allow(value):\n"
        "    return value\n"
        "\n"
        "@allow\n"
        "def normalize_name(value: str) -> str:\n"
        "    return value.strip()\n",
        encoding="utf-8",
    )
    responsibility = _responsibility(
        responsibility_id="normalize_name",
        intent="normalize name",
        lifecycle="active",
        path="src/bpfw/catalog/helpers.py",
        symbol="normalize_name",
    )
    responsibility["location"]["symbol_type"] = "function"
    responsibility["location"]["start_line"] = 5
    responsibility["location"]["end_line"] = 6

    rendered = "\n".join(
        build_code_lines(
            project_root=tmp_path,
            responsibility=responsibility,
        )
    )

    assert "  4  @allow" in rendered
    assert "  5  def normalize_name(value: str) -> str:" in rendered


def test_code_preview_includes_multiline_decorator_block(tmp_path: Path) -> None:
    source_path = tmp_path / "src" / "bpfw" / "catalog"
    source_path.mkdir(parents=True)
    (source_path / "models.py").write_text(
        "def decorate(*_args, **_kwargs):\n"
        "    def wrapper(target):\n"
        "        return target\n"
        "    return wrapper\n"
        "\n"
        "@decorate(\n"
        "    first=True,\n"
        "    second=True,\n"
        ")\n"
        "@decorate(third=True)\n"
        "class DecoratedModel:\n"
        "    value: str\n",
        encoding="utf-8",
    )
    responsibility = _responsibility(
        responsibility_id="decorated_model",
        intent="define model",
        lifecycle="active",
        path="src/bpfw/catalog/models.py",
        symbol="DecoratedModel",
    )
    responsibility["location"]["symbol_type"] = "class"
    responsibility["location"]["start_line"] = 11
    responsibility["location"]["end_line"] = 12

    rendered = "\n".join(
        build_code_lines(
            project_root=tmp_path,
            responsibility=responsibility,
        )
    )

    assert "  6  @decorate(" in rendered
    assert "  7      first=True," in rendered
    assert "  8      second=True," in rendered
    assert "  9  )" in rendered
    assert " 10  @decorate(third=True)" in rendered
    assert " 11  class DecoratedModel:" in rendered


def test_text_inspector_edits_fields_and_accepts(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text(
        "version: 1\n"
        "responsibilities:\n"
        "  - id: example\n"
        "    name: ExampleService\n"
        "    domain: ''\n"
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
            "6maintain example",
            "gcatalog",
            "x",
            "o reviewed",
            "",
        ]
    )
    output: list[str] = []

    exit_code = run_text_inspector_session(
        session=session,
        input_func=lambda _prompt: next(answers),
        print_func=output.append,
    )

    saved = blueprint_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "maintain example" in saved
    assert "experimental" in saved
    assert "reviewed" in saved


def test_text_inspector_save_next_persists_partial_fields(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text(
        "version: 1\n"
        "responsibilities:\n"
        "  - id: example\n"
        "    name: ExampleService\n"
        "    domain: catalog\n"
        "    lifecycle: active\n"
        "    intent: ''\n",
        encoding="utf-8",
    )
    session = load_inspect_session(project_root=tmp_path)
    answers = iter(["6maintain partial example", ""])
    output: list[str] = []

    exit_code = run_text_inspector_session(
        session=session,
        input_func=lambda _prompt: next(answers),
        print_func=output.append,
    )

    saved = blueprint_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "maintain partial example" in saved
    assert not any("Missing required fields" in line for line in output)


def test_text_inspector_unknown_command_stays_on_current_item(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text(
        "version: 1\n"
        "responsibilities:\n"
        "  - id: example\n"
        "    name: ExampleService\n"
        "    domain: ''\n"
        "    lifecycle: active\n"
        "    intent: ''\n"
        "    location:\n"
        "      path: src/bpfw/catalog/example.py\n"
        "      symbol: ExampleService\n"
        "      symbol_type: class\n",
        encoding="utf-8",
    )
    session = load_inspect_session(project_root=tmp_path)
    answers = iter(["???", "6maintain example", ""])
    output: list[str] = []

    exit_code = run_text_inspector_session(
        session=session,
        input_func=lambda _prompt: next(answers),
        print_func=output.append,
    )

    rendered = "\n".join(output)
    saved = blueprint_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "Unknown command" in rendered
    assert rendered.count("Blueprint Framework Inspector") >= 2
    assert "maintain example" in saved


def test_text_inspector_blocks_when_input_is_unavailable(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text(
        "version: 1\n"
        "responsibilities:\n"
        "  - id: example\n"
        "    name: ExampleService\n"
        "    lifecycle: ''\n"
        "    intent: ''\n",
        encoding="utf-8",
    )
    session = load_inspect_session(project_root=tmp_path)
    output: list[str] = []

    def unavailable_input(_prompt: str) -> str:
        raise EOFError

    exit_code = run_text_inspector_session(
        session=session,
        input_func=unavailable_input,
        print_func=output.append,
    )

    saved = blueprint_path.read_text(encoding="utf-8")
    assert exit_code == 1
    assert "Interactive inspector input unavailable." in output
    assert "exampleservice:example" not in saved


def test_text_inspector_accepts_new_detected_code(tmp_path: Path) -> None:
    source_path = tmp_path / "src" / "demo"
    source_path.mkdir(parents=True)
    (source_path / "app.py").write_text(
        "def declared_func():\n"
        "    return 1\n"
        "\n"
        "def extra_func():\n"
        "    return 2\n",
        encoding="utf-8",
    )
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text(
        "version: 1\n"
        "project:\n"
        "  source_roots:\n"
        "    - src\n"
        "  ignored_paths:\n"
        "    - tests\n"
        "responsibilities:\n"
        "  - id: declared_func\n"
        "    intent: maintain declared func\n"
        "    name: declared_func\n"
        "    domain: demo\n"
        "    lifecycle: active\n"
        "    location:\n"
        "      path: src/demo/app.py\n"
        "      module: src.demo.app\n"
        "      symbol: declared_func\n"
        "      symbol_type: function\n",
        encoding="utf-8",
    )
    output: list[str] = []
    answers = iter(
        [
            "6maintain extra func",
            "g demo",
            "",
        ]
    )

    exit_code = run_text_inspector(
        project_root=tmp_path,
        input_func=lambda _prompt: next(answers),
        print_func=output.append,
    )

    rendered = "\n".join(output)
    saved = blueprint_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "Blueprint Framework Inspector" in rendered
    assert "maintain extra func" in saved
    assert "extra_func" in saved


def test_text_inspector_back_returns_to_saved_previous_item(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text(
        "version: 1\n"
        "responsibilities:\n"
        "  - id: first\n"
        "    name: FirstService\n"
        "    domain: ''\n"
        "    lifecycle: ''\n"
        "    intent: ''\n"
        "    location:\n"
        "      path: src/bpfw/catalog/first.py\n"
        "      module: src.bpfw.catalog.first\n"
        "      symbol: FirstService\n"
        "      symbol_type: class\n"
        "  - id: second\n"
        "    name: SecondService\n"
        "    domain: ''\n"
        "    lifecycle: ''\n"
        "    intent: ''\n"
        "    location:\n"
        "      path: src/bpfw/catalog/second.py\n"
        "      module: src.bpfw.catalog.second\n"
        "      symbol: SecondService\n"
        "      symbol_type: class\n",
        encoding="utf-8",
    )
    session = load_inspect_session(project_root=tmp_path)
    answers = iter(["6first intent", "gfirst_domain", "", "b", "q"])
    output: list[str] = []

    exit_code = run_text_inspector_session(
        session=session,
        input_func=lambda _prompt: next(answers),
        print_func=output.append,
    )

    rendered = "\n".join(output)
    assert exit_code == 0
    assert "1/2 draft" in rendered
    assert "2/2 draft" in rendered
    assert rendered.count("1/2 draft") >= 2
    assert "INTENT     first intent" in rendered
    assert "DOMAIN     first_domain" in rendered


def test_text_inspector_custom_intent_uses_slot_six_with_prompt(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text(
        "version: 1\n"
        "responsibilities:\n"
        "  - id: example\n"
        "    name: ExampleService\n"
        "    domain: catalog\n"
        "    lifecycle: active\n"
        "    intent: ''\n"
        "    location:\n"
        "      path: src/bpfw/catalog/example.py\n"
        "      symbol: ExampleService\n"
        "      symbol_type: class\n",
        encoding="utf-8",
    )
    session = load_inspect_session(project_root=tmp_path)
    answers = iter(["6", "prompted custom intent", ""])
    output: list[str] = []

    exit_code = run_text_inspector_session(
        session=session,
        input_func=lambda _prompt: next(answers),
        print_func=output.append,
    )

    saved = blueprint_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "prompted custom intent" in saved
