from pathlib import Path

from bpfw.commands.status import run_status


def test_status_recommends_init_when_blueprint_is_missing(tmp_path: Path) -> None:
    output, exit_code = run_status(project_root=tmp_path)

    assert exit_code == 0
    assert "Suggested next command:\n  bpfw init" in output
    assert "Reason:\n  No blueprint authority exists yet." in output


def test_status_recommends_inspect_for_undeclared_code(tmp_path: Path) -> None:
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

    output, exit_code = run_status(project_root=tmp_path)

    assert exit_code == 1
    assert "Suggested next command:\n  bpfw inspector" in output
    assert "Some detected code units are not declared or are incomplete." in output


def test_status_recommends_lock_for_valid_unlocked_blueprint(tmp_path: Path) -> None:
    source_path = tmp_path / "src" / "demo"
    source_path.mkdir(parents=True)
    (source_path / "app.py").write_text(
        "def declared_func():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text(
        "version: 1\n"
        "project:\n"
        "  source_roots:\n"
        "    - src\n"
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

    output, exit_code = run_status(project_root=tmp_path)

    assert exit_code == 0
    assert "Suggested next command:\n  bpfw lock" in output
    assert "The blueprint authority is valid but unlocked." in output
