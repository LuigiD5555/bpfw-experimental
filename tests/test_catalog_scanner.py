from pathlib import Path

from bpfw.catalog.scanner import scan_python_project


def test_scanner_orders_dependencies_before_dependents(tmp_path: Path) -> None:
    """Verify dependency-first topological ordering: dependencies reviewed before dependents."""
    source_root = tmp_path / "src"
    source_root.mkdir()
    (source_root / "example.py").write_text(
        "def helper_function(value: str) -> str:\n"
        "    return value.upper()\n"
        "\n"
        "def processor_function(data: str) -> str:\n"
        "    result = helper_function(data)\n"
        "    return result.strip()\n"
        "\n"
        "def main_function() -> None:\n"
        "    processed = processor_function('hello world')\n"
        "    print(processed)\n",
        encoding="utf-8",
    )

    scan_result = scan_python_project(
        project_root=tmp_path,
        source_roots=["src"],
        ignored_paths=[],
    )

    # Extract just the symbols in order
    ordered_symbols = [unit.symbol for unit in scan_result.discovered_units]
    
    # Find indices
    helper_idx = ordered_symbols.index("helper_function")
    processor_idx = ordered_symbols.index("processor_function")
    main_idx = ordered_symbols.index("main_function")
    
    # Verify dependency ordering:
    # - helper_function (no dependencies) should be first
    # - processor_function (calls helper_function) should be after helper
    # - main_function (calls processor_function) should be last
    assert helper_idx < processor_idx, (
        f"helper_function should come before processor_function: "
        f"helper={helper_idx}, processor={processor_idx}"
    )
    assert processor_idx < main_idx, (
        f"processor_function should come before main_function: "
        f"processor={processor_idx}, main={main_idx}"
    )
    
    # Verify the full order matches dependency-first
    assert ordered_symbols == [
        "helper_function",
        "processor_function",
        "main_function",
    ]


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
            ["src.demo.Service.method.nested_in_method.nested_deeper"],
        ),
        (
            "Service.method",
            "method",
            2,
            7,
            [],
            ["src.demo.Service.method.nested_in_method"],
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
            ["src.demo.Service.InnerClass.inner_method"],
            [],
        ),
        (
            "Service",
            "class",
            1,
            11,
            ["src.demo.Service.method"],
            ["src.demo.Service.InnerClass"],
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
            ["src.demo.top_function.nested_function"],
        ),
    ]
