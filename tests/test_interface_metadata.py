"""Tests for interface metadata support in Blueprint Framework."""

from pathlib import Path

from bpfw.catalog.scanner import extract_interface_metadata


def test_function_inputs_and_output(tmp_path: Path) -> None:
    """Test that scanner extracts function inputs and output with annotations."""
    source_file = tmp_path / "test_module.py"
    source_file.write_text(
        "def process_data(value: int, count: int = 0) -> str:\n"
        "    return str(value * count)\n",
        encoding="utf-8",
    )

    import ast
    source = source_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_file))

    func_node = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "process_data":
            func_node = node
            break

    assert func_node is not None

    inputs, output = extract_interface_metadata(
        node=func_node,
        symbol_type="function",
        class_body=None,
    )

    assert len(inputs) == 2
    assert inputs[0]["name"] == "value"
    assert inputs[0]["type"] == "int"
    assert inputs[0]["default"] is None
    assert inputs[0]["required"] is True
    assert inputs[0]["description"] is None

    assert inputs[1]["name"] == "count"
    assert inputs[1]["type"] == "int"
    assert inputs[1]["default"] == 0
    assert inputs[1]["required"] is False
    assert inputs[1]["description"] is None

    assert output is not None
    assert output["type"] == "str"
    assert output["description"] is None


def test_function_no_annotations(tmp_path: Path) -> None:
    """Test that scanner handles functions without type annotations."""
    source_file = tmp_path / "test_module.py"
    source_file.write_text(
        "def process(x, y):\n"
        "    return x + y\n",
        encoding="utf-8",
    )

    import ast
    source = source_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_file))

    func_node = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "process":
            func_node = node
            break

    assert func_node is not None

    inputs, output = extract_interface_metadata(
        node=func_node,
        symbol_type="function",
        class_body=None,
    )

    assert len(inputs) == 2
    assert inputs[0]["name"] == "x"
    assert inputs[0]["type"] is None
    assert inputs[0]["default"] is None
    assert inputs[0]["required"] is True

    assert inputs[1]["name"] == "y"
    assert inputs[1]["type"] is None
    assert inputs[1]["default"] is None
    assert inputs[1]["required"] is True

    assert output is None


def test_function_default_values(tmp_path: Path) -> None:
    """Test that scanner extracts default values correctly."""
    source_file = tmp_path / "test_module.py"
    source_file.write_text(
        'def func(a: int, b: str = "hello", c: bool = True, d=None) -> None:\n'
        "    pass\n",
        encoding="utf-8",
    )

    import ast
    source = source_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_file))

    func_node = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "func":
            func_node = node
            break

    assert func_node is not None

    inputs, output = extract_interface_metadata(
        node=func_node,
        symbol_type="function",
        class_body=None,
    )

    assert len(inputs) == 4

    assert inputs[0]["name"] == "a"
    assert inputs[0]["type"] == "int"
    assert inputs[0]["default"] is None
    assert inputs[0]["required"] is True

    assert inputs[1]["name"] == "b"
    assert inputs[1]["type"] == "str"
    assert inputs[1]["default"] == "hello"
    assert inputs[1]["required"] is False

    assert inputs[2]["name"] == "c"
    assert inputs[2]["type"] == "bool"
    assert inputs[2]["default"] is True
    assert inputs[2]["required"] is False

    assert inputs[3]["name"] == "d"
    assert inputs[3]["type"] is None
    assert inputs[3]["default"] is None
    assert inputs[3]["required"] is False

    assert output is not None
    assert output["type"] == "None"
    assert output["description"] is None


def test_class_init_inputs(tmp_path: Path) -> None:
    """Test that scanner extracts class __init__ inputs and excludes self."""
    source_file = tmp_path / "test_module.py"
    source_file.write_text(
        "class Service:\n"
        "    def __init__(self, name: str, port: int = 8080):\n"
        "        self.name = name\n"
        "        self.port = port\n",
        encoding="utf-8",
    )

    import ast
    source = source_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_file))

    class_node = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Service":
            class_node = node
            break

    assert class_node is not None

    inputs, output = extract_interface_metadata(
        node=class_node,
        symbol_type="class",
        class_body=class_node.body,
    )

    # self should be excluded
    assert len(inputs) == 2

    assert inputs[0]["name"] == "name"
    assert inputs[0]["type"] == "str"
    assert inputs[0]["default"] is None
    assert inputs[0]["required"] is True

    assert inputs[1]["name"] == "port"
    assert inputs[1]["type"] == "int"
    assert inputs[1]["default"] == 8080
    assert inputs[1]["required"] is False

    assert output is None  # __init__ typically returns None


def test_class_no_init(tmp_path: Path) -> None:
    """Test that scanner handles classes without __init__."""
    source_file = tmp_path / "test_module.py"
    source_file.write_text(
        "class SimpleClass:\n"
        "    pass\n",
        encoding="utf-8",
    )

    import ast
    source = source_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_file))

    class_node = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "SimpleClass":
            class_node = node
            break

    assert class_node is not None

    inputs, output = extract_interface_metadata(
        node=class_node,
        symbol_type="class",
        class_body=class_node.body,
    )

    assert inputs == []
    assert output is None


def test_method_excludes_self(tmp_path: Path) -> None:
    """Test that scanner excludes self from method signatures."""
    source_file = tmp_path / "test_module.py"
    source_file.write_text(
        "class Service:\n"
        "    def process(self, data: str) -> bool:\n"
        "        return bool(data)\n",
        encoding="utf-8",
    )

    import ast
    source = source_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_file))

    func_node = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Service":
            for stmt in node.body:
                if isinstance(stmt, ast.FunctionDef) and stmt.name == "process":
                    func_node = stmt
                    break
            break

    assert func_node is not None

    inputs, output = extract_interface_metadata(
        node=func_node,
        symbol_type="method",
        class_body=None,
    )

    # self should be excluded
    assert len(inputs) == 1
    assert inputs[0]["name"] == "data"
    assert inputs[0]["type"] == "str"
    assert inputs[0]["default"] is None
    assert inputs[0]["required"] is True

    assert output is not None
    assert output["type"] == "bool"


def test_classmethod_excludes_cls(tmp_path: Path) -> None:
    """Test that scanner excludes cls from classmethod signatures."""
    source_file = tmp_path / "test_module.py"
    source_file.write_text(
        "class Factory:\n"
        "    @classmethod\n"
        "    def create(cls, name: str):\n"
        "        return Factory()\n",
        encoding="utf-8",
    )

    import ast
    source = source_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_file))

    func_node = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Factory":
            for stmt in node.body:
                if isinstance(stmt, ast.FunctionDef) and stmt.name == "create":
                    func_node = stmt
                    break
            break

    assert func_node is not None

    inputs, output = extract_interface_metadata(
        node=func_node,
        symbol_type="method",
        class_body=None,
    )

    # cls should be excluded
    assert len(inputs) == 1
    assert inputs[0]["name"] == "name"
    assert inputs[0]["type"] == "str"
    assert inputs[0]["default"] is None
    assert inputs[0]["required"] is True

    # No return annotation
    assert output is None


def test_canonical_blueprint_no_interface(tmp_path: Path) -> None:
    """Test that old blueprint entries without interface still load and work."""
    # This is a basic sanity check that the interface key is optional
    from bpfw.catalog.loader import BlueprintLoader

    # Create a simple blueprint without interface
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)

    blueprint_path.write_text(
        "version: 1\n"
        "project:\n"
        "  id: test_project\n"
        "  name: test_project\n"
        "  root: .\n"
        "  language: python\n"
        "  source_roots:\n"
        "  - src\n"
        "  ignored_paths:\n"
        "  - .git\n"
        "policy:\n"
        "  mode: catalog\n"
        "  empty_blueprint_allows_execution: true\n"
        "  defined_blueprint_blocks_on_drift: true\n"
        "  allowed_statuses:\n"
        "  - active\n"
        "  - experimental\n"
        "  single_active_per_purpose: true\n"
        "  undeclared_code_blocks: true\n"
        "  missing_declared_code_blocks: true\n"
        "  security:\n"
        "    no_secrets_in_blueprint: true\n"
        "    public_safe_mode: true\n"
        "    detected_detail_level: minimal\n"
        "blocks:\n"
        "- id: simple_function\n"
        "  purpose: test simple_function\n"
        "  name: simple_function\n"
        "  domain: test\n"
        "  status: active\n"
        "  code:\n"
        "    path: src/test.py\n"
        "    module: src.test\n"
        "    symbol: simple_function\n"
        "    kind: function\n"
        "    start_line: 1\n"
        "    end_line: 3\n"
        "  detected:\n"
        "    qualified_name: src.test.simple_function\n"
        "    kind: function\n"
        "  entrypoints: []\n"
        "  connections: []\n"
        "  uniqueness:\n"
        "    group: test_simple_function\n"
        "    allow_multiple_non_active: true\n"
        "    forbid_active_duplicates: true\n"
        "    suspected_duplicates: []\n"
        "  replacement:\n"
        "    replaces: null\n"
        "    replaced_by: null\n"
        "    reason: null\n"
        "  notes: null\n",
        encoding="utf-8",
    )

    loader = BlueprintLoader(project_root=tmp_path)
    load_result = loader.load()

    # Should load successfully
    assert load_result.state == "defined"
    assert len(load_result.data.get("blocks", [])) == 1

    block = load_result.data["blocks"][0]
    # Interface should not be present (or should be None)
    assert block.get("interface") is None or block.get("interface") == {}


def test_scan_python_project_includes_interface(tmp_path: Path) -> None:
    """Test that scan_python_project includes interface metadata."""
    from bpfw.catalog.scanner import scan_python_project

    source_root = tmp_path / "src"
    source_root.mkdir()

    (source_root / "example.py").write_text(
        "class Calculator:\n"
        "    def __init__(self, name: str):\n"
        "        self.name = name\n"
        "\n"
        "    def add(self, a: int, b: int) -> int:\n"
        "        return a + b\n"
        "\n"
        "def multiply(x: int, y: int) -> int:\n"
        "    return x * y\n",
        encoding="utf-8",
    )

    scan_result = scan_python_project(
        project_root=tmp_path,
        source_roots=["src"],
        ignored_paths=[],
    )

    discovered_units = scan_result.discovered_units

    # Should find 3 units: Calculator, Calculator.add, multiply
    assert len(discovered_units) >= 2

    # Find Calculator class
    calculator = None
    for unit in discovered_units:
        # Match by symbol name (could be with or without src prefix)
        if "example.Calculator" in unit.symbol or unit.symbol == "Calculator":
            calculator = unit
            break

    assert calculator is not None, f"Calculator not found in {[u.symbol for u in discovered_units]}"
    # Calculator should have interface from __init__
    assert len(calculator.interface_inputs) == 1
    assert calculator.interface_inputs[0]["name"] == "name"
    assert calculator.interface_inputs[0]["type"] == "str"
    assert calculator.interface_output is None  # __init__ returns None

    # Verify that other units also have interface metadata
    # Look for any unit with multiply-like interface
    found_multiply = False
    for unit in discovered_units:
        if "multiply" in unit.symbol or unit.symbol.endswith("multiply"):
            assert len(unit.interface_inputs) == 2
            assert unit.interface_inputs[0]["name"] == "x"
            assert unit.interface_inputs[1]["name"] == "y"
            assert unit.interface_output is not None
            assert unit.interface_output["type"] == "int"
            found_multiply = True
            break

    assert found_multiply, "Could not find multiply function in discovered units"
