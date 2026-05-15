"""Tests for the catalog inspector module."""
from pathlib import Path

from bpfw.catalog.domain_suggestions import suggest_domains
from bpfw.catalog.purpose_suggestions import suggest_purposes
from bpfw.integrations.inspector.base import (
    InspectIssue,
    apply_automatic_authority_fields,
    backfill_detected_docstring_from_source,
    build_code_lines,
    get_incomplete_blocks,
    load_inspect_session,
)
from bpfw.integrations.inspector.commands import InspectorAction, apply_inspector_command
from bpfw.integrations.inspector.screen import render_inspector_screen
from bpfw.integrations.inspector.session import run_text_inspector, run_text_inspector_session


def _responsibility(
    responsibility_id: str,
    purpose: str,
    status: str,
    path: str = "src/bpfw/catalog/example.py",
    symbol: str = "ExampleService",
) -> dict:
    return {
        "id": responsibility_id,
        "purpose": purpose,
        "name": symbol,
        "domain": None,
        "status": status,
        "code": {
            "path": path,
            "symbol": symbol,
            "kind": "class",
            "start_line": 2,
            "end_line": 4,
        },
        "uniqueness": {
            "group": None,
            "allow_multiple_non_active": True,
            "forbid_active_duplicates": True,
            "suspected_duplicates": [],
        },
        "connections": [],
        "replacement": {
            "replaces": None,
            "replaced_by": None,
            "reason": None,
        },
    }


def test_suggest_domain_from_source_package_path() -> None:
    block = _responsibility(
        responsibility_id="example",
        purpose="maintain example",
        status="active",
        path="src/bpfw/protection/authority.py",
    )

    # Get first non-empty slot from fixed list
    domains = suggest_domains(block)
    first_domain = domains[0]
    assert first_domain != "-"


def test_suggest_domains_returns_list() -> None:
    block = _responsibility(
        responsibility_id="example",
        purpose="maintain example",
        status="active",
        path="src/bpfw/protection/authority.py",
    )

    domains = suggest_domains(block)
    assert isinstance(domains, list)
    assert len(domains) == 6  # Fixed 6 slots
    assert all(isinstance(d, str) for d in domains)
    # Last slot is custom domain
    assert domains[-1] == "custom"


def test_suggest_domains_ignores_package_roots() -> None:
    block = _responsibility(
        responsibility_id="purpose_suggestions",
        purpose="suggest purposes",
        status="active",
        path="src/bpfw/catalog/purpose_suggestions.py",
        symbol="PurposeSuggestion",
    )

    suggestions = suggest_domains(block)
    # Technical stopwords like "src" are filtered
    assert "src" not in suggestions
    # Package names may appear in suggestions
    assert len(suggestions) == 6  # Fixed 6 slots


def test_suggest_domain_returns_first_domain_suggestion() -> None:
    block = _responsibility(
        responsibility_id="purpose_suggestions",
        purpose="suggest purposes",
        status="active",
        path="src/bpfw/catalog/purpose_suggestions.py",
        symbol="PurposeSuggestion",
    )

    # Get first slot from fixed list
    domains = suggest_domains(block)
    first_domain = domains[0]
    assert isinstance(first_domain, str)
    assert first_domain != "-"  # Should not be a placeholder


def test_inspector_domain_shortcuts_use_qwerty_and_y_custom() -> None:
    issue = _responsibility("example", "maintain example", "active")
    action = apply_inspector_command(
        command="t",
        issue=InspectIssue(issue_type="draft", block=issue),
        purpose_suggestions=[],
        domain_suggestions=["one", "two", "three", "four", "five"],
        input_func=lambda _prompt: "",
    )

    assert action == InspectorAction.STAY
    assert issue["domain"] == "five"

    action = apply_inspector_command(
        command="ycustom_domain",
        issue=InspectIssue(issue_type="draft", block=issue),
        purpose_suggestions=[],
        domain_suggestions=[],
        input_func=lambda _prompt: "",
    )

    assert action == InspectorAction.STAY
    assert issue["domain"] == "custom_domain"


def test_get_incomplete_blocks_detects_missing_fields() -> None:
    complete = _responsibility("example", "maintain example", "active")
    complete["domain"] = "example"
    incomplete = _responsibility("missing", "maintain example", "active")
    incomplete["domain"] = ""
    blueprint_data = {"blocks": [complete, incomplete]}

    assert get_incomplete_blocks(blueprint_data) == [incomplete]


def test_apply_automatic_authority_fields_derives_groups() -> None:
    active_one = _responsibility("user_creation", "create user", "active")
    active_two = _responsibility(
        "account_registration",
        "create user",
        "active",
        path="src/bpfw/catalog/accounts.py",
        symbol="AccountRegistration",
    )
    blueprint_data = {"blocks": [active_one, active_two]}

    apply_automatic_authority_fields(blueprint_data)

    assert active_one["uniqueness"]["group"] == "create_user"
    assert active_two["uniqueness"]["group"] == "create_user"
    assert active_one["uniqueness"]["suspected_duplicates"] == [
        "account_registration"
    ]


def test_text_inspector_renders_expected_sections(tmp_path: Path) -> None:
    block = _responsibility(
        responsibility_id="example",
        purpose="",
        status="active",
        path="src/bpfw/catalog/example.py",
    )
    block["detected"] = {
        "methods": ["ExampleService.run"],
        "functions": ["ExampleService.Helper"],
    }
    output: list[str] = []
    purpose_suggestions = suggest_purposes(block)
    domain_suggestions = suggest_domains(block)

    render_inspector_screen(
        project_root=tmp_path,
        issue_type="draft",
        block=block,
        index=11,
        total=82,
        purpose_suggestions=purpose_suggestions,
        domain_suggestions=domain_suggestions,
        print_func=output.append,
    )

    rendered = "\n".join(output)
    assert "Blueprint Framework Inspector" in rendered
    assert "Block Status" in rendered
    assert "Purpose suggestions" in rendered
    assert "[6] write custom purpose" in rendered
    assert "Domain suggestions" in rendered
    assert " [q] " in rendered
    assert " [w] " in rendered
    assert " [e] " in rendered
    assert " [r] " in rendered
    assert " [t] " in rendered
    assert "[y] write custom domain" in rendered
    assert "Hierarchy" not in rendered
    assert "Interface" not in rendered
    assert "Notes" not in rendered
    assert "[a] full view" in rendered
    assert "[z] active" in rendered
    assert "[x] experimental" in rendered
    assert "[c] legacy" in rendered
    assert "[v] deprecated" in rendered
    assert "[Enter] save + next" in rendered
    assert "Type a command key and press Enter" in rendered
    assert "a + Enter" in rendered
    assert "ctrl+c to quit" in rendered
    commands_section = rendered[rendered.rindex("Commands"):]
    assert "purpose suggestion" not in commands_section
    assert "custom purpose" not in commands_section
    assert "custom domain" not in commands_section
    assert "[z|x|c|v] status" not in commands_section
    assert "[n] name" not in commands_section
    assert "[i] interface" not in commands_section
    assert "[o] notes" not in commands_section
    assert "├" in rendered
    assert "s save" not in rendered
    assert "l1" not in rendered
    assert "d1" not in rendered


def test_text_inspector_all_view_renders_extended_sections(tmp_path: Path) -> None:
    block = _responsibility(
        responsibility_id="example",
        purpose="",
        status="active",
        path="src/bpfw/catalog/example.py",
    )
    block["detected"] = {
        "methods": ["ExampleService.run"],
        "functions": ["ExampleService.Helper"],
    }
    output: list[str] = []
    purpose_suggestions = suggest_purposes(block)
    domain_suggestions = suggest_domains(block)

    render_inspector_screen(
        project_root=tmp_path,
        issue_type="draft",
        block=block,
        index=11,
        total=82,
        purpose_suggestions=purpose_suggestions,
        domain_suggestions=domain_suggestions,
        print_func=output.append,
        show_all=True,
    )

    rendered = "\n".join(output)
    assert "Hierarchy" in rendered
    assert "children:" in rendered
    assert "ExampleService.run" in rendered
    assert "Interface" in rendered
    assert "Notes" in rendered
    assert "[a] compact view" in rendered
    commands_section = rendered[rendered.rindex("Commands"):]
    assert "purpose suggestion" in commands_section
    assert "custom purpose" in commands_section
    assert "custom domain" in commands_section
    assert "[z|x|c|v] status" in commands_section
    assert "[n] name" in commands_section
    assert "[i] interface" in commands_section
    assert "[o] notes" in commands_section
    assert "1 + Enter" in commands_section


def test_backfill_detected_docstring_from_source(tmp_path: Path) -> None:
    source_path = tmp_path / "src" / "bpfw" / "protection"
    source_path.mkdir(parents=True)
    (source_path / "authority.py").write_text(
        "from pathlib import Path\n"
        "\n"
        "def resolve_protected_resources(project_root: Path):\n"
        "    \"\"\"Build the full protection resource list for a project, including its blueprint and BPFW guard files.\"\"\"\n"
        "    return []\n",
        encoding="utf-8",
    )
    block = _responsibility(
        responsibility_id="resolve_protected_resources",
        purpose="",
        status="active",
        path="src/bpfw/protection/authority.py",
        symbol="resolve_protected_resources",
    )
    block["code"]["kind"] = "function"
    block["code"]["start_line"] = 3
    block["detected"] = {}

    backfill_detected_docstring_from_source(project_root=tmp_path, block=block)

    assert block["detected"]["docstring"].startswith("Build the full protection resource list")


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
    block = _responsibility(
        responsibility_id="looks_like_absolute_path",
        purpose="absolute_path_checker",
        status="active",
        path="src/bpfw/catalog/security.py",
        symbol="looks_like_absolute_path",
    )
    block["code"]["kind"] = "function"
    block["code"]["start_line"] = 1
    block["code"]["end_line"] = 3

    rendered = "\n".join(
        build_code_lines(
            project_root=tmp_path,
            block=block,
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
    block = _responsibility(
        responsibility_id="looks_like_absolute_path",
        purpose="absolute_path_checker",
        status="active",
        path="src/bpfw/catalog/security.py",
        symbol="looks_like_absolute_path",
    )
    block["code"]["kind"] = "function"
    block["code"]["start_line"] = 4
    block["code"]["end_line"] = 5

    rendered = "\n".join(
        build_code_lines(
            project_root=tmp_path,
            block=block,
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
    block = _responsibility(
        responsibility_id="looks_like_absolute_path",
        purpose="absolute_path_checker",
        status="active",
        path="src/bpfw/catalog/security.py",
        symbol="looks_like_absolute_path",
    )
    block["code"]["kind"] = "function"
    block["code"]["start_line"] = 1
    block["code"]["end_line"] = 3

    rendered = "\n".join(
        build_code_lines(
            project_root=tmp_path,
            block=block,
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
    block = _responsibility(
        responsibility_id="looks_like_absolute_path",
        purpose="absolute_path_checker",
        status="active",
        path="src/bpfw/catalog/security.py",
        symbol="looks_like_absolute_path",
    )
    block["code"]["kind"] = "function"
    block["code"]["start_line"] = 1
    block["code"]["end_line"] = 3

    rendered = "\n".join(
        build_code_lines(
            project_root=tmp_path,
            block=block,
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
    block = _responsibility(
        responsibility_id="domain_suggestion",
        purpose="suggest domain",
        status="active",
        path="src/bpfw/catalog/domain_suggestions.py",
        symbol="DomainSuggestion",
    )
    block["code"]["kind"] = "class"
    block["code"]["start_line"] = 4
    block["code"]["end_line"] = 5

    rendered = "\n".join(
        build_code_lines(
            project_root=tmp_path,
            block=block,
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
    block = _responsibility(
        responsibility_id="normalize_name",
        purpose="normalize name",
        status="active",
        path="src/bpfw/catalog/helpers.py",
        symbol="normalize_name",
    )
    block["code"]["kind"] = "function"
    block["code"]["start_line"] = 5
    block["code"]["end_line"] = 6

    rendered = "\n".join(
        build_code_lines(
            project_root=tmp_path,
            block=block,
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
    block = _responsibility(
        responsibility_id="decorated_model",
        purpose="define model",
        status="active",
        path="src/bpfw/catalog/models.py",
        symbol="DecoratedModel",
    )
    block["code"]["kind"] = "class"
    block["code"]["start_line"] = 11
    block["code"]["end_line"] = 12

    rendered = "\n".join(
        build_code_lines(
            project_root=tmp_path,
            block=block,
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
        "blocks:\n"
        "  - id: example\n"
        "    name: ExampleService\n"
        "    domain: ''\n"
        "    status: ''\n"
        "    purpose: ''\n"
        "    notes: ''\n"
        "    code:\n"
        "      path: src/bpfw/catalog/example.py\n"
        "      symbol: ExampleService\n"
        "      kind: class\n"
        "      start_line: 1\n"
        "      end_line: 1\n",
        encoding="utf-8",
    )
    session = load_inspect_session(project_root=tmp_path)
    answers = iter(
        [
            "6maintain example",
            "ycatalog",
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
        "blocks:\n"
        "  - id: example\n"
        "    name: ExampleService\n"
        "    domain: catalog\n"
        "    status: active\n"
        "    purpose: ''\n",
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
        "blocks:\n"
        "  - id: example\n"
        "    name: ExampleService\n"
        "    domain: ''\n"
        "    status: active\n"
        "    purpose: ''\n"
        "    code:\n"
        "      path: src/bpfw/catalog/example.py\n"
        "      symbol: ExampleService\n"
        "      kind: class\n",
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
        "blocks:\n"
        "  - id: example\n"
        "    name: ExampleService\n"
        "    status: ''\n"
        "    purpose: ''\n",
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


def test_text_inspector_stops_cleanly_on_keyboard_interrupt(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text(
        "version: 1\n"
        "blocks:\n"
        "  - id: example\n"
        "    name: ExampleService\n"
        "    domain: catalog\n"
        "    status: active\n"
        "    purpose: ''\n"
        "    code:\n"
        "      path: src/bpfw/catalog/example.py\n"
        "      symbol: ExampleService\n"
        "      kind: class\n",
        encoding="utf-8",
    )
    session = load_inspect_session(project_root=tmp_path)
    output: list[str] = []

    def interrupting_input(_prompt: str) -> str:
        raise KeyboardInterrupt

    exit_code = run_text_inspector_session(
        session=session,
        input_func=interrupting_input,
        print_func=output.append,
    )

    saved = blueprint_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "Inspector stopped." in output
    assert "purpose: ''" in saved


def test_text_inspector_keyboard_interrupt_in_interface_editor_returns_to_main(
    tmp_path: Path,
) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text(
        "version: 1\n"
        "blocks:\n"
        "  - id: example\n"
        "    name: ExampleService\n"
        "    domain: catalog\n"
        "    status: active\n"
        "    purpose: ''\n"
        "    code:\n"
        "      path: src/bpfw/catalog/example.py\n"
        "      symbol: ExampleService\n"
        "      kind: class\n",
        encoding="utf-8",
    )
    session = load_inspect_session(project_root=tmp_path)
    output: list[str] = []
    command_stream: list[object] = [
        "i",
        "a",
        KeyboardInterrupt(),
        "6maintain example",
        "",
    ]

    def scripted_input(_prompt: str) -> str:
        next_value = command_stream.pop(0)
        if isinstance(next_value, BaseException):
            raise next_value
        return str(next_value)

    exit_code = run_text_inspector_session(
        session=session,
        input_func=scripted_input,
        print_func=output.append,
    )

    rendered = "\n".join(output)
    saved = blueprint_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "Interface editor cancelled." in rendered
    assert "Saved." in rendered
    assert "maintain example" in saved


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
        "blocks:\n"
        "  - id: declared_func\n"
        "    purpose: maintain declared func\n"
        "    name: declared_func\n"
        "    domain: demo\n"
        "    status: active\n"
        "    code:\n"
        "      path: src/demo/app.py\n"
        "      module: src.demo.app\n"
        "      symbol: declared_func\n"
        "      kind: function\n",
        encoding="utf-8",
    )
    output: list[str] = []
    answers = iter(
        [
            "6maintain extra func",
            "y demo",
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
        "blocks:\n"
        "  - id: first\n"
        "    name: FirstService\n"
        "    domain: ''\n"
        "    status: ''\n"
        "    purpose: ''\n"
        "    code:\n"
        "      path: src/bpfw/catalog/first.py\n"
        "      module: src.bpfw.catalog.first\n"
        "      symbol: FirstService\n"
        "      kind: class\n"
        "  - id: second\n"
        "    name: SecondService\n"
        "    domain: ''\n"
        "    status: ''\n"
        "    purpose: ''\n"
        "    code:\n"
        "      path: src/bpfw/catalog/second.py\n"
        "      module: src.bpfw.catalog.second\n"
        "      symbol: SecondService\n"
        "      kind: class\n",
        encoding="utf-8",
    )
    session = load_inspect_session(project_root=tmp_path)
    answers = iter(["6first purpose", "yfirst_domain", "", "b", "quit"])
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
    # Purpose and domain values are shown, not old labels
    assert "first purpose" in rendered
    assert "first_domain" in rendered


def test_text_inspector_custom_purpose_uses_slot_six_with_prompt(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text(
        "version: 1\n"
        "blocks:\n"
        "  - id: example\n"
        "    name: ExampleService\n"
        "    domain: catalog\n"
        "    status: active\n"
        "    purpose: ''\n"
        "    code:\n"
        "      path: src/bpfw/catalog/example.py\n"
        "      symbol: ExampleService\n"
        "      kind: class\n",
        encoding="utf-8",
    )
    session = load_inspect_session(project_root=tmp_path)
    answers = iter(["6", "prompted custom purpose", ""])
    output: list[str] = []

    exit_code = run_text_inspector_session(
        session=session,
        input_func=lambda _prompt: next(answers),
        print_func=output.append,
    )

    saved = blueprint_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "prompted custom purpose" in saved

def test_suggest_domains_uses_previous_domain_for_same_origin_slot_t() -> None:
    previous = _responsibility(
        responsibility_id="previous_error",
        purpose="raise previous error",
        status="active",
        path="src/bpfw/core/errors.py",
        symbol="PreviousError",
    )
    previous["domain"] = "exceptions"
    previous["code"]["module"] = "src.bpfw.core.errors"

    current = _responsibility(
        responsibility_id="blueprint_locked_error",
        purpose="",
        status="active",
        path="src/bpfw/core/errors.py",
        symbol="BlueprintLockedError",
    )
    current["code"]["module"] = "src.bpfw.core.errors"

    suggestions = suggest_domains(current, project_blocks=[previous, current])

    assert suggestions[4] == "exceptions"


def test_suggest_domains_previous_origin_slot_ignores_other_modules() -> None:
    previous = _responsibility(
        responsibility_id="previous_error",
        purpose="raise previous error",
        status="active",
        path="src/bpfw/protection/errors.py",
        symbol="PreviousError",
    )
    previous["domain"] = "protection"
    previous["code"]["module"] = "src.bpfw.protection.errors"

    current = _responsibility(
        responsibility_id="blueprint_locked_error",
        purpose="",
        status="active",
        path="src/bpfw/core/errors.py",
        symbol="BlueprintLockedError",
    )
    current["code"]["module"] = "src.bpfw.core.errors"

    suggestions = suggest_domains(current, project_blocks=[previous, current])

    assert suggestions[4] == "-"


def test_inspector_help_explains_suggestion_sources() -> None:
    """Ensure inspector help explains purpose and domain suggestion slots."""

    from bpfw.integrations.inspector.session import _render_help_block

    rendered = "\n".join(_render_help_block())

    assert "Purpose suggestions" in rendered
    assert "[1] Existing purpose from blueprint matches this block." in rendered
    assert "[2] Learned purpose previously accepted by the user." in rendered
    assert "[3] Symbol or block name, such as class/function name." in rendered
    assert "[4] Docstring first sentence or supported docstring pattern." in rendered
    assert "[5] Blended evidence from history, symbol, and docstring." in rendered
    assert "Domain suggestions" in rendered
    assert "[q] Folder-based domain from the nearest useful folder." in rendered
    assert "[w] File-based domain from the source file name." in rendered
    assert "[e] Module-based domain from the Python module parent." in rendered
    assert "[r] Symbol-based domain from the class/function name." in rendered
    assert "[t] Previous domain used for the same code origin." in rendered


def test_compact_inspector_help_omits_full_mode_details() -> None:
    """Ensure compact inspector help hides full-mode explanations."""

    from bpfw.integrations.inspector.session import _render_help_block

    rendered = "\n".join(_render_help_block(show_all=False))

    assert "Interface modes" not in rendered
    assert "Why '-' appears" not in rendered
    assert "Editing" not in rendered
    assert "Lifecycle" in rendered
    assert "Two active blocks should not share" in rendered
    assert "the same purpose." in rendered


def test_full_inspector_help_keeps_full_mode_details() -> None:
    """Ensure full inspector help keeps full-mode explanations."""

    from bpfw.integrations.inspector.session import _render_help_block

    rendered = "\n".join(_render_help_block(show_all=True))

    assert "Interface modes" in rendered
    assert "Why '-' appears" in rendered
    assert "'-' means that source did not have enough evidence." in rendered
    assert "Editing" in rendered
    assert "[n]        Edit name" in rendered
    assert "Lifecycle" in rendered
    assert "experimental  Being tested or not fully accepted yet." in rendered


def test_inspector_input_reader_uses_custom_input_function() -> None:
    """Inspector input reader must preserve scripted test input functions."""

    from bpfw.integrations.inspector.input_adapter import InspectorInputReader

    received_prompts: list[str] = []

    def fake_input(prompt: str) -> str:
        """Return a scripted value and keep the prompt for assertions."""

        received_prompts.append(prompt)
        return "scripted value"

    reader = InspectorInputReader(fake_input)

    assert reader.read("purpose: ") == "scripted value"
    assert received_prompts == ["purpose: "]
