"""Generic dependency-first review ordering tests.

These tests prove the ordering system works correctly for any Python project,
not just BPFW-specific code.
"""

from pathlib import Path

from bpfw.core.catalog.scanner import scan_python_project


def test_method_calls_method_declared_below_it(tmp_path: Path) -> None:
    """Test 1: Method calls method declared below it.
    
    Expected: Service.child before Service.parent
    """
    source_root = tmp_path / "src"
    source_root.mkdir()
    (source_root / "service.py").write_text(
        "class Service:\n"
        "    def parent(self):\n"
        "        return self.child()\n"
        "\n"
        "    def child(self):\n"
        "        return \"value\"\n",
        encoding="utf-8",
    )

    scan_result = scan_python_project(
        project_root=tmp_path,
        source_roots=["src"],
        ignored_paths=[],
    )

    ordered_symbols = [unit.symbol for unit in scan_result.discovered_units]
    
    parent_idx = ordered_symbols.index("Service.parent")
    child_idx = ordered_symbols.index("Service.child")
    
    assert child_idx < parent_idx, (
        f"Service.child should come before Service.parent: "
        f"child={child_idx}, parent={parent_idx}"
    )


def test_authority_document_same_class_dependencies(tmp_path: Path) -> None:
    """Test 2: AuthorityDocument-style same-class dependencies.
    
    Expected:
    - AuthorityDocument.origin_for_block before AuthorityDocument.shard_for_block
    - AuthorityDocument.shard_by_path before AuthorityDocument.shard_for_block
    """
    source_root = tmp_path / "src"
    source_root.mkdir()
    (source_root / "document.py").write_text(
        "class AuthorityDocument:\n"
        "    def shard_for_block(self, block_id):\n"
        "        shard_path = self.origin_for_block(block_id)\n"
        "        if shard_path is None:\n"
        "            return None\n"
        "        return self.shard_by_path(shard_path)\n"
        "\n"
        "    def origin_for_block(self, block_id):\n"
        "        return self.block_origins.get(block_id)\n"
        "\n"
        "    def shard_by_path(self, shard_path):\n"
        "        return self.shards.get(shard_path)\n",
        encoding="utf-8",
    )

    scan_result = scan_python_project(
        project_root=tmp_path,
        source_roots=["src"],
        ignored_paths=[],
    )

    ordered_symbols = [unit.symbol for unit in scan_result.discovered_units]
    
    origin_idx = ordered_symbols.index("AuthorityDocument.origin_for_block")
    shard_idx = ordered_symbols.index("AuthorityDocument.shard_by_path")
    for_block_idx = ordered_symbols.index("AuthorityDocument.shard_for_block")
    
    assert origin_idx < for_block_idx, (
        f"origin_for_block should come before shard_for_block: "
        f"origin={origin_idx}, for_block={for_block_idx}"
    )
    assert shard_idx < for_block_idx, (
        f"shard_by_path should come before shard_for_block: "
        f"shard={shard_idx}, for_block={for_block_idx}"
    )


def test_same_method_name_different_classes_no_collision(tmp_path: Path) -> None:
    """Test 3: Same method name in different classes must not collide.
    
    Expected:
    - ClassA.helper before ClassA.worker
    - ClassB.helper must not be treated as a dependency of ClassA.worker
    """
    source_root = tmp_path / "src"
    source_root.mkdir()
    (source_root / "classes.py").write_text(
        "class ClassA:\n"
        "    def worker(self):\n"
        "        return self.helper()\n"
        "\n"
        "    def helper(self):\n"
        "        return \"a\"\n"
        "\n"
        "\n"
        "class ClassB:\n"
        "    def helper(self):\n"
        "        return \"b\"\n",
        encoding="utf-8",
    )

    scan_result = scan_python_project(
        project_root=tmp_path,
        source_roots=["src"],
        ignored_paths=[],
    )

    ordered_symbols = [unit.symbol for unit in scan_result.discovered_units]
    
    worker_idx = ordered_symbols.index("ClassA.worker")
    helper_a_idx = ordered_symbols.index("ClassA.helper")
    
    assert helper_a_idx < worker_idx, (
        f"ClassA.helper should come before ClassA.worker: "
        f"helper_a={helper_a_idx}, worker={worker_idx}"
    )
    # ClassB.helper should be discovered but its position doesn't matter
    assert "ClassB.helper" in ordered_symbols, "ClassB.helper should be discovered"


def test_attribute_method_call_no_false_dependency(tmp_path: Path) -> None:
    """Test 4: Attribute method call must not create false dependency.
    
    Expected:
    Service.get_blocks must NOT be forced before Service.parent only because
    shard.get_blocks has the same tail name.
    """
    source_root = tmp_path / "src"
    source_root.mkdir()
    (source_root / "service.py").write_text(
        "class Service:\n"
        "    def parent(self, shard):\n"
        "        return shard.get_blocks()\n"
        "\n"
        "    def get_blocks(self):\n"
        "        return []\n",
        encoding="utf-8",
    )

    scan_result = scan_python_project(
        project_root=tmp_path,
        source_roots=["src"],
        ignored_paths=[],
    )

    ordered_symbols = [unit.symbol for unit in scan_result.discovered_units]
    
    parent_idx = ordered_symbols.index("Service.parent")
    get_blocks_idx = ordered_symbols.index("Service.get_blocks")
    
    # Service.get_blocks should NOT be forced before Service.parent
    # because shard.get_blocks() is an arbitrary object method call
    # The actual relative order depends on source order, but we verify
    # that no false dependency was created by checking that parent
    # can still appear before get_blocks if it's declared first
    # In this case, parent is declared first (line 2), so it should be first
    assert parent_idx < get_blocks_idx, (
        f"Service.parent should come before Service.get_blocks (by source order): "
        f"parent={parent_idx}, get_blocks={get_blocks_idx}"
    )


def test_chained_attribute_method_call_no_false_dependency(tmp_path: Path) -> None:
    """Test 5: Chained attribute method call must not create false dependency.
    
    Expected:
    Service.get_authority_config must NOT be forced before Service.parent
    only because self.index.get_authority_config has the same tail name.
    """
    source_root = tmp_path / "src"
    source_root.mkdir()
    (source_root / "service.py").write_text(
        "class Service:\n"
        "    def parent(self):\n"
        "        return self.index.get_authority_config()\n"
        "\n"
        "    def get_authority_config(self):\n"
        "        return {}\n",
        encoding="utf-8",
    )

    scan_result = scan_python_project(
        project_root=tmp_path,
        source_roots=["src"],
        ignored_paths=[],
    )

    ordered_symbols = [unit.symbol for unit in scan_result.discovered_units]
    
    parent_idx = ordered_symbols.index("Service.parent")
    get_config_idx = ordered_symbols.index("Service.get_authority_config")
    
    # Service.get_authority_config should NOT be forced before Service.parent
    # because self.index.get_authority_config() is a chained attribute call
    # The actual relative order depends on source order
    # In this case, parent is declared first (line 2), so it should be first
    assert parent_idx < get_config_idx, (
        f"Service.parent should come before Service.get_authority_config (by source order): "
        f"parent={parent_idx}, get_config={get_config_idx}"
    )


def test_nested_function_child_first_ordering(tmp_path: Path) -> None:
    """Test 6: Nested function child-first ordering.
    
    Expected:
    - Service.method.nested_in_method.nested_deeper
    before
    - Service.method.nested_in_method
    before
    - Service.method
    """
    source_root = tmp_path / "src"
    source_root.mkdir()
    (source_root / "service.py").write_text(
        "class Service:\n"
        "    def method(self):\n"
        "        def nested_in_method():\n"
        "            def nested_deeper():\n"
        "                return \"deep\"\n"
        "            return nested_deeper()\n"
        "        return nested_in_method()\n",
        encoding="utf-8",
    )

    scan_result = scan_python_project(
        project_root=tmp_path,
        source_roots=["src"],
        ignored_paths=[],
    )

    ordered_symbols = [unit.symbol for unit in scan_result.discovered_units]
    
    deeper_idx = ordered_symbols.index("Service.method.nested_in_method.nested_deeper")
    nested_idx = ordered_symbols.index("Service.method.nested_in_method")
    method_idx = ordered_symbols.index("Service.method")
    
    assert deeper_idx < nested_idx, (
        f"nested_deeper should come before nested_in_method: "
        f"deeper={deeper_idx}, nested={nested_idx}"
    )
    assert nested_idx < method_idx, (
        f"nested_in_method should come before method: "
        f"nested={nested_idx}, method={method_idx}"
    )


def test_module_level_function_declared_below_caller(tmp_path: Path) -> None:
    """Test 7: Module-level function declared below caller.
    
    Expected: helper before main
    """
    source_root = tmp_path / "src"
    source_root.mkdir()
    (source_root / "main.py").write_text(
        "def main():\n"
        "    return helper()\n"
        "\n"
        "\n"
        "def helper():\n"
        "    return \"value\"\n",
        encoding="utf-8",
    )

    scan_result = scan_python_project(
        project_root=tmp_path,
        source_roots=["src"],
        ignored_paths=[],
    )

    ordered_symbols = [unit.symbol for unit in scan_result.discovered_units]
    
    main_idx = ordered_symbols.index("main")
    helper_idx = ordered_symbols.index("helper")
    
    assert helper_idx < main_idx, (
        f"helper should come before main: "
        f"helper={helper_idx}, main={main_idx}"
    )


def test_cycle_safety(tmp_path: Path) -> None:
    """Test 8: Cycle safety.

    Expected:
    - No infinite recursion
    - Both Service.a and Service.b appear exactly once
    - Algorithm terminates (doesn't hang)
    
    Note: When A→B and B→A (a cycle), we cannot satisfy both
    dependency ordering AND source order. Our algorithm breaks cycles
    by skipping already-visiting nodes, which results in one valid ordering.
    """
    source_root = tmp_path / "src"
    source_root.mkdir()
    (source_root / "service.py").write_text(
        "class Service:\n"
        "    def a(self):\n"
        "        return self.b()\n"
        "\n"
        "    def b(self):\n"
        "        return self.a()\n",
        encoding="utf-8",
    )

    scan_result = scan_python_project(
        project_root=tmp_path,
        source_roots=["src"],
        ignored_paths=[],
    )

    ordered_symbols = [unit.symbol for unit in scan_result.discovered_units]

    # Both methods should appear exactly once
    assert ordered_symbols.count("Service.a") == 1, "Service.a should appear exactly once"
    assert ordered_symbols.count("Service.b") == 1, "Service.b should appear exactly once"

    # Both should be in the order (along with the class itself)
    assert "Service.a" in ordered_symbols, "Service.a should be in ordered symbols"
    assert "Service.b" in ordered_symbols, "Service.b should be in ordered symbols"
    assert "Service" in ordered_symbols, "Service class should be in ordered symbols"

    # Check that b comes before a (due to cycle resolution)
    b_idx = ordered_symbols.index("Service.b")
    a_idx = ordered_symbols.index("Service.a")
    assert b_idx < a_idx, (
        f"Service.b should come before Service.a (cycle resolution): "
        f"b={b_idx}, a={a_idx}"
    )
