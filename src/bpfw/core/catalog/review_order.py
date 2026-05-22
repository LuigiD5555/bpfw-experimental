"""Review ordering logic for cognitive dependency-first traversal.

The review order is dependency-first: if code block A uses code block B,
then B must be reviewed before A.

This implementation:
- Uses qualified_name as the only canonical identifier
- Extracts structured calls with context (self.method, shard.get_blocks, etc.)
- Resolves references using strict scope rules
- Does not create false dependencies from arbitrary method calls
"""

from collections import defaultdict
from typing import Dict, List, Set

from bpfw.core.catalog.models import DiscoveredCodeUnit


def order_blocks_for_review(units: List[DiscoveredCodeUnit]) -> List[DiscoveredCodeUnit]:
    """
    Return units ordered from dependencies to dependents.
    
    The order guarantees:
    1. Containment: nested functions/classes come before their containers
    2. Dependencies: called methods/functions come before their callers
    3. Stability: source order breaks ties when no dependency exists
    
    Args:
        units: List of discovered code units.
        
    Returns:
        Units in dependency-first order.
    """
    if not units:
        return []
    
    # Build canonical index using only qualified_name
    index = {unit.qualified_name: unit for unit in units}
    
    # Build dependency graph using only qualified_name
    graph = _build_dependency_graph(units, index)
    
    # Topologically sort with cycle safety
    ordered = _topological_sort(graph, index)
    
    return ordered


def _build_dependency_graph(
    units: List[DiscoveredCodeUnit],
    index: Dict[str, DiscoveredCodeUnit],
) -> Dict[str, List[str]]:
    """
    Build dependency graph where edges point from dependents to dependencies.
    
    If unit A depends on unit B, then graph[A] contains B.
    This means A will come after B in the final order.
    
    Args:
        units: List of discovered code units.
        index: Canonical index mapping qualified_name to DiscoveredCodeUnit.
        
    Returns:
        Dependency graph as dict {dependent_qualified_name: [dependency_qualified_name, ...]}.
    """
    graph: Dict[str, List[str]] = defaultdict(list)
    
    for unit in units:
        # Add containment dependencies (children before parents)
        for child_qualified_name in unit.methods + unit.functions:
            if child_qualified_name in index:
                graph[unit.qualified_name].append(child_qualified_name)
        
        # Add call dependencies based on structured calls
        for call in unit.calls:
            resolved = _resolve_call(call, unit, index)
            if resolved:
                graph[unit.qualified_name].append(resolved)
    
    return graph


def _resolve_call(
    call: Dict,
    caller: DiscoveredCodeUnit,
    index: Dict[str, DiscoveredCodeUnit],
) -> str | None:
    """
    Resolve a structured call to a discovered code unit.
    
    Resolution rules:
    1. self.method_name() → method in same class
    2. cls.method_name() → method in same class
    3. bare_name() → nested/enclosing/module-level function
    4. ClassName() → class constructor
    5. Arbitrary object methods (shard.get_blocks()) are NOT resolved
    6. Chained attributes (self.index.get_config()) are NOT resolved
    
    Args:
        call: Structured call dict with keys 'context', 'name'.
        caller: The unit making the call.
        index: Canonical index of all discovered units.
        
    Returns:
        Qualified name of the discovered unit, or None if not resolved.
    """
    context = call.get("context")
    name = call.get("name")
    
    if not name:
        return None
    
    # Rule 1 & 2: self.method_name() or cls.method_name() → same class method
    if context in ("self", "cls"):
        return _resolve_same_class_method(name, caller, index)
    
    # Rule 3: bare_name() → nested/enclosing/module-level function
    if context is None:
        return _resolve_bare_function(name, caller, index)
    
    # Rule 4: ClassName() → class constructor
    if context is None and name[0].isupper():
        return _resolve_class_constructor(name, caller, index)
    
    # Rules 5 & 6: Do NOT resolve arbitrary object method calls or chained calls
    # These require runtime type information we don't have
    return None


def _resolve_same_class_method(
    method_name: str,
    caller: DiscoveredCodeUnit,
    index: Dict[str, DiscoveredCodeUnit],
) -> str | None:
    """
    Resolve self.method_name() or cls.method_name() to same class method.
    
    Args:
        method_name: The method name being called.
        caller: The unit making the call.
        index: Canonical index of all discovered units.
        
    Returns:
        Qualified name of the method in the same class, or None.
    """
    # Caller must be a method in a class
    if caller.symbol_type != "method":
        return None
    
    # Extract class name from caller's symbol
    parts = caller.symbol.split(".")
    if len(parts) < 2:
        return None
    
    class_symbol = ".".join(parts[:-1])
    target_qualified = f"{caller.module}.{class_symbol}.{method_name}"
    
    if target_qualified in index:
        return target_qualified
    
    return None


def _resolve_bare_function(
    function_name: str,
    caller: DiscoveredCodeUnit,
    index: Dict[str, DiscoveredCodeUnit],
) -> str | None:
    """
    Resolve bare_name() to nested/enclosing/module-level function.
    
    Resolution order:
    1. Nested function in current scope
    2. Enclosing function/method
    3. Module-level function
    
    Args:
        function_name: The function name being called.
        caller: The unit making the call.
        index: Canonical index of all discovered units.
        
    Returns:
        Qualified name of the function, or None.
    """
    # Try nested function (if caller is a function/method with nested functions)
    for nested_name in caller.functions:
        if nested_name.endswith(f".{function_name}"):
            if nested_name in index:
                return nested_name
    
    # Try module-level function
    module_qualified = f"{caller.module}.{function_name}"
    if module_qualified in index:
        module_unit = index[module_qualified]
        # Only resolve if it's a top-level function (not a method)
        if module_unit.symbol_type == "function":
            return module_qualified
    
    return None


def _resolve_class_constructor(
    class_name: str,
    caller: DiscoveredCodeUnit,
    index: Dict[str, DiscoveredCodeUnit],
) -> str | None:
    """
    Resolve ClassName() to a discovered class.
    
    Args:
        class_name: The class name being constructed.
        caller: The unit making the call.
        index: Canonical index of all discovered units.
        
    Returns:
        Qualified name of the class, or None.
    """
    # Try module-level class
    module_qualified = f"{caller.module}.{class_name}"
    if module_qualified in index:
        module_unit = index[module_qualified]
        # Only resolve if it's a class
        if module_unit.symbol_type in ("class", "nested_class"):
            return module_qualified
    
    return None


def _topological_sort(
    graph: Dict[str, List[str]],
    index: Dict[str, DiscoveredCodeUnit],
) -> List[DiscoveredCodeUnit]:
    """
    Topologically sort dependency graph with cycle safety.
    
    Uses DFS with cycle detection. Cycles are broken by keeping the
    nodes that form the cycle in stable source order.
    
    Args:
        graph: Dependency graph {dependent: [dependencies]}.
        index: Canonical index mapping qualified_name to DiscoveredCodeUnit.
        
    Returns:
        Units in dependency-first order.
    """
    ordered: List[DiscoveredCodeUnit] = []
    visited: Set[str] = set()
    visiting: Set[str] = set()
    
    # Process nodes in stable source order for deterministic output
    all_qualified_names = sorted(
        index.keys(),
        key=lambda qn: (
            index[qn].path,
            index[qn].start_line or 0,
            index[qn].symbol,
        ),
    )
    
    for qualified_name in all_qualified_names:
        _visit_node(
            node=qualified_name,
            graph=graph,
            index=index,
            visited=visited,
            visiting=visiting,
            ordered=ordered,
        )
    
    return ordered


def _visit_node(
    node: str,
    graph: Dict[str, List[str]],
    index: Dict[str, DiscoveredCodeUnit],
    visited: Set[str],
    visiting: Set[str],
    ordered: List[DiscoveredCodeUnit],
) -> None:
    """
    Visit a node in topological DFS.
    
    Args:
        node: Qualified name of the node to visit.
        graph: Dependency graph.
        index: Canonical index mapping qualified_name to DiscoveredCodeUnit.
        visited: Set of fully visited nodes.
        visiting: Set of nodes currently being visited (for cycle detection).
        ordered: Accumulated ordered units.
    """
    if node in visited:
        return
    
    if node in visiting:
        # Cycle detected - this dependency is already being visited.
        # Skip it to avoid infinite recursion, but continue processing.
        return
    
    visiting.add(node)
    
    # Visit dependencies first
    for dependency in graph.get(node, []):
        if dependency not in visited and dependency in index:
            _visit_node(
                node=dependency,
                graph=graph,
                index=index,
                visited=visited,
                visiting=visiting,
                ordered=ordered,
            )
    
    visiting.remove(node)
    visited.add(node)
    
    # Add to ordered list after all dependencies are processed
    if node in index:
        ordered.append(index[node])
