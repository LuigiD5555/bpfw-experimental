"""Test dependency-first review ordering for blocks."""

from bpfw.catalog.review_order import order_blocks_for_review
from bpfw.catalog.models import DiscoveredCodeUnit


def test_simple_dependency_ordering():
    """Test that dependencies are ordered before dependents."""
    units = [
        DiscoveredCodeUnit(
            path="test.py",
            module="test",
            symbol="MyClass.method_a",
            symbol_type="method",
            qualified_name="test.MyClass.method_a",
            start_line=10,
            end_line=15,
            methods=[],
            functions=[],
            imports=[],
            decorators=[],
            docstring=None,
            signature=None,
            interface_inputs=[],
            interface_output=None,
            called_symbols=["helper"],
        ),
        DiscoveredCodeUnit(
            path="test.py",
            module="test",
            symbol="MyClass.helper",
            symbol_type="method",
            qualified_name="test.MyClass.helper",
            start_line=1,
            end_line=5,
            methods=[],
            functions=[],
            imports=[],
            decorators=[],
            docstring=None,
            signature=None,
            interface_inputs=[],
            interface_output=None,
            called_symbols=[],
        ),
    ]
    
    ordered = order_blocks_for_review(units)
    symbols = [unit.symbol for unit in ordered]
    
    # helper should come before method_a (dependency-first)
    assert symbols.index("MyClass.helper") < symbols.index("MyClass.method_a")


def test_same_class_preference_for_collision():
    """Test that same-class methods are preferred over other classes."""
    units = [
        DiscoveredCodeUnit(
            path="test.py",
            module="test",
            symbol="ClassA.worker",
            symbol_type="method",
            qualified_name="test.ClassA.worker",
            start_line=20,
            end_line=25,
            methods=[],
            functions=[],
            imports=[],
            decorators=[],
            docstring=None,
            signature=None,
            interface_inputs=[],
            interface_output=None,
            called_symbols=["helper"],
        ),
        DiscoveredCodeUnit(
            path="test.py",
            module="test",
            symbol="ClassA.helper",
            symbol_type="method",
            qualified_name="test.ClassA.helper",
            start_line=1,
            end_line=5,
            methods=[],
            functions=[],
            imports=[],
            decorators=[],
            docstring=None,
            signature=None,
            interface_inputs=[],
            interface_output=None,
            called_symbols=[],
        ),
        DiscoveredCodeUnit(
            path="test.py",
            module="test",
            symbol="ClassB.helper",
            symbol_type="method",
            qualified_name="test.ClassB.helper",
            start_line=10,
            end_line=15,
            methods=[],
            functions=[],
            imports=[],
            decorators=[],
            docstring=None,
            signature=None,
            interface_inputs=[],
            interface_output=None,
            called_symbols=[],
        ),
    ]
    
    ordered = order_blocks_for_review(units)
    symbols = [unit.symbol for unit in ordered]
    
    # ClassA.worker should depend on ClassA.helper (not ClassB.helper)
    worker_idx = symbols.index("ClassA.worker")
    class_a_helper_idx = symbols.index("ClassA.helper")
    class_b_helper_idx = symbols.index("ClassB.helper")
    
    # Both helpers should come before worker
    assert class_a_helper_idx < worker_idx
    assert class_b_helper_idx < worker_idx
    
    # ClassA.helper should come before ClassB.helper (same class first)
    assert class_a_helper_idx < class_b_helper_idx


def test_chain_of_dependencies():
    """Test that chains of dependencies are resolved correctly."""
    units = [
        DiscoveredCodeUnit(
            path="test.py",
            module="test",
            symbol="MyClass.top_level",
            symbol_type="method",
            qualified_name="test.MyClass.top_level",
            start_line=30,
            end_line=35,
            methods=[],
            functions=[],
            imports=[],
            decorators=[],
            docstring=None,
            signature=None,
            interface_inputs=[],
            interface_output=None,
            called_symbols=["middle"],
        ),
        DiscoveredCodeUnit(
            path="test.py",
            module="test",
            symbol="MyClass.middle",
            symbol_type="method",
            qualified_name="test.MyClass.middle",
            start_line=20,
            end_line=25,
            methods=[],
            functions=[],
            imports=[],
            decorators=[],
            docstring=None,
            signature=None,
            interface_inputs=[],
            interface_output=None,
            called_symbols=["bottom"],
        ),
        DiscoveredCodeUnit(
            path="test.py",
            module="test",
            symbol="MyClass.bottom",
            symbol_type="method",
            qualified_name="test.MyClass.bottom",
            start_line=10,
            end_line=15,
            methods=[],
            functions=[],
            imports=[],
            decorators=[],
            docstring=None,
            signature=None,
            interface_inputs=[],
            interface_output=None,
            called_symbols=[],
        ),
    ]
    
    ordered = order_blocks_for_review(units)
    symbols = [unit.symbol for unit in ordered]
    
    # Dependency order: bottom -> middle -> top_level
    assert symbols == ["MyClass.bottom", "MyClass.middle", "MyClass.top_level"]


def test_real_world_authority_repository_scenario():
    """Test the specific scenario from the user's report.
    
    AuthorityRepository.get_shard_for_block should be ordered after:
    - AuthorityRepository.get_origin
    - Any methods called on self.shards (though these are dict operations, not methods)
    """
    units = [
        DiscoveredCodeUnit(
            path="authority/repository.py",
            module="bpfw.authority.repository",
            symbol="AuthorityRepository.get_shard_for_block",
            symbol_type="method",
            qualified_name="bpfw.authority.repository.AuthorityRepository.get_shard_for_block",
            start_line=87,
            end_line=99,
            methods=[],
            functions=[],
            imports=[],
            decorators=[],
            docstring="Get the AuthorityShard that contains a block.",
            signature="get_shard_for_block(block_id: str) -> AuthorityShard | None",
            interface_inputs=[{"name": "block_id", "type": "str"}],
            interface_output={"type": "AuthorityShard | None"},
            called_symbols=["get", "get_origin"],
        ),
        DiscoveredCodeUnit(
            path="authority/repository.py",
            module="bpfw.authority.repository",
            symbol="AuthorityRepository.get_origin",
            symbol_type="method",
            qualified_name="bpfw.authority.repository.AuthorityRepository.get_origin",
            start_line=60,
            end_line=85,
            methods=[],
            functions=[],
            imports=[],
            decorators=[],
            docstring="Get the origin shard path for a block ID.",
            signature="get_origin(block_id: str) -> str | None",
            interface_inputs=[{"name": "block_id", "type": "str"}],
            interface_output={"type": "str | None"},
            called_symbols=["get_shards"],
        ),
        DiscoveredCodeUnit(
            path="authority/repository.py",
            module="bpfw.authority.repository",
            symbol="AuthorityRepository.get_shards",
            symbol_type="method",
            qualified_name="bpfw.authority.repository.AuthorityRepository.get_shards",
            start_line=40,
            end_line=58,
            methods=[],
            functions=[],
            imports=[],
            decorators=[],
            docstring="Get all authority shards.",
            signature="get_shards() -> dict[str, AuthorityShard]",
            interface_inputs=[],
            interface_output={"type": "dict[str, AuthorityShard]"},
            called_symbols=[],
        ),
    ]
    
    ordered = order_blocks_for_review(units)
    symbols = [unit.symbol for unit in ordered]
    
    # Dependencies should come before dependents
    get_shards_idx = symbols.index("AuthorityRepository.get_shards")
    get_origin_idx = symbols.index("AuthorityRepository.get_origin")
    get_shard_for_block_idx = symbols.index("AuthorityRepository.get_shard_for_block")
    
    # get_shards -> get_origin -> get_shard_for_block
    assert get_shards_idx < get_origin_idx < get_shard_for_block_idx


def test_no_circular_dependencies_cause_infinite_loop():
    """Test that circular dependencies don't cause infinite loops."""
    units = [
        DiscoveredCodeUnit(
            path="test.py",
            module="test",
            symbol="ClassA.method_a",
            symbol_type="method",
            qualified_name="test.ClassA.method_a",
            start_line=10,
            end_line=15,
            methods=[],
            functions=[],
            imports=[],
            decorators=[],
            docstring=None,
            signature=None,
            interface_inputs=[],
            interface_output=None,
            called_symbols=["method_b"],
        ),
        DiscoveredCodeUnit(
            path="test.py",
            module="test",
            symbol="ClassB.method_b",
            symbol_type="method",
            qualified_name="test.ClassB.method_b",
            start_line=20,
            end_line=25,
            methods=[],
            functions=[],
            imports=[],
            decorators=[],
            docstring=None,
            signature=None,
            interface_inputs=[],
            interface_output=None,
            called_symbols=["method_a"],
        ),
    ]
    
    # This should complete without hanging
    ordered = order_blocks_for_review(units)
    
    # Both should be in the result
    assert len(ordered) == 2