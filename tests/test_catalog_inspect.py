from pathlib import Path

from bpfw.integrations.inspect_base import (
    apply_automatic_authority_fields,
    build_code_lines,
    get_incomplete_responsibilities,
    suggest_domain,
)
from bpfw.integrations.inspect_base import load_inspect_session
from bpfw.integrations.inspect_text import (
    render_text_screen,
    run_text_inspect,
    run_text_inspect_session,
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
        "canonical_name": symbol,
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


def test_get_incomplete_responsibilities_detects_missing_fields() -> None:
    complete = _responsibility("example", "maintain example", "active")
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


def test_text_inspect_renders_expected_sections(tmp_path: Path) -> None:
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

    render_text_screen(
        project_root=tmp_path,
        issue_type="draft",
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
    assert "Nested snippets" in rendered
    assert "ExampleService.run" in rendered
    assert "ExampleService.Helper" in rendered
    assert "[i] intent" in rendered
    assert "[n] name" in rendered
    assert "[d] domain" in rendered
    assert "[l] lifecycle" in rendered
    assert "[o] observations" in rendered
    assert "[s] save + next" in rendered
    assert "[b] back" in rendered
    assert "[h] help" in rendered
    assert "[q] quit" in rendered


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


def test_text_inspect_edits_fields_and_accepts(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text(
        "version: 1\n"
        "responsibilities:\n"
        "  - id: example\n"
        "    canonical_name: ExampleService\n"
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
            "i",
            "maintain example",
            "d",
            "catalog",
            "l",
            "experimental",
            "o",
            "reviewed",
            "s",
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


def test_text_inspect_save_next_persists_partial_fields(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text(
        "version: 1\n"
        "responsibilities:\n"
        "  - id: example\n"
        "    canonical_name: ''\n"
        "    domain: catalog\n"
        "    lifecycle: active\n"
        "    intent: maintain example\n",
        encoding="utf-8",
    )
    session = load_inspect_session(project_root=tmp_path)
    answers = iter(["i", "maintain partial example", "s"])
    output: list[str] = []

    exit_code = run_text_inspect_session(
        session=session,
        input_func=lambda _prompt: next(answers),
        print_func=output.append,
    )

    saved = blueprint_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "maintain partial example" in saved
    assert not any("Missing required fields" in line for line in output)


def test_text_inspect_help_explains_actions_and_stays_on_current_item(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text(
        "version: 1\n"
        "responsibilities:\n"
        "  - id: example\n"
        "    canonical_name: ExampleService\n"
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
    answers = iter(["h", "", "i", "maintain example", "s"])
    output: list[str] = []

    exit_code = run_text_inspect_session(
        session=session,
        input_func=lambda _prompt: next(answers),
        print_func=output.append,
    )

    rendered = "\n".join(output)
    saved = blueprint_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "BPFW Inspect Help" in rendered
    assert "d  domain" in rendered
    assert "Press Enter to return to inspect." in rendered
    assert rendered.count("BPFW Inspect  1/1  draft") >= 2
    assert "maintain example" in saved


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


def test_text_inspect_accepts_new_detected_code(tmp_path: Path) -> None:
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
        "    canonical_name: declared_func\n"
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
            "i",
            "maintain extra func",
            "d",
            "demo",
            "s",
        ]
    )

    exit_code = run_text_inspect(
        project_root=tmp_path,
        input_func=lambda _prompt: next(answers),
        print_func=output.append,
    )

    rendered = "\n".join(output)
    saved = blueprint_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "BPFW Inspect  1/1  new_detected" in rendered
    assert "src/demo/app.py :: extra_func" in rendered
    assert "maintain extra func" in saved
    assert "extra_func" in saved
