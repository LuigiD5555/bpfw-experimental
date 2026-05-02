from pathlib import Path

from bpfw.catalog.scanner import scan_python_project


def test_scanner_discovers_nested_code_units_child_before_parent(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (source_root / "demo.py").write_text(
        "class Service:\n"
        "    def method(self):\n"
        "        def nested_in_method():\n"
        "            def nested_deeper():\n"
        "                return 'deep'\n"
        "            return nested_deeper()\n"
        "        return nested_in_method()\n"
        "\n"
        "    class InnerClass:\n"
        "        def inner_method(self):\n"
        "            return 'inner'\n"
        "\n"
        "\n"
        "def top_function():\n"
        "    def nested_function():\n"
        "        return 'nested'\n"
        "    return nested_function()\n",
        encoding="utf-8",
    )

    scan_result = scan_python_project(
        project_root=tmp_path,
        source_roots=["src"],
        ignored_paths=[],
    )

    discovered = [
        (
            unit.symbol,
            unit.symbol_type,
            unit.start_line,
            unit.end_line,
            unit.methods,
            unit.functions,
        )
        for unit in scan_result.discovered_units
    ]
    assert discovered == [
        (
            "Service.method.nested_in_method.nested_deeper",
            "nested_function",
            4,
            5,
            [],
            [],
        ),
        (
            "Service.method.nested_in_method",
            "nested_function",
            3,
            6,
            [],
            ["Service.method.nested_in_method.nested_deeper"],
        ),
        (
            "Service.method",
            "method",
            2,
            7,
            [],
            ["Service.method.nested_in_method"],
        ),
        (
            "Service.InnerClass.inner_method",
            "method",
            10,
            11,
            [],
            [],
        ),
        (
            "Service.InnerClass",
            "nested_class",
            9,
            11,
            ["Service.InnerClass.inner_method"],
            [],
        ),
        (
            "Service",
            "class",
            1,
            11,
            ["Service.method"],
            ["Service.InnerClass"],
        ),
        (
            "top_function.nested_function",
            "nested_function",
            15,
            16,
            [],
            [],
        ),
        (
            "top_function",
            "function",
            14,
            17,
            [],
            ["top_function.nested_function"],
        ),
    ]
