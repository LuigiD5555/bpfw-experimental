
"""Review ordering logic for cognitive dependency-first traversal."""

from collections import defaultdict
from typing import Dict, List, Set

from bpfw.catalog.models import DiscoveredCodeUnit


def order_blocks_for_review(units: List[DiscoveredCodeUnit]) -> List[DiscoveredCodeUnit]:
    """Return units ordered from dependencies to dependents."""

    symbol_index = _build_symbol_index(units)
    dependency_graph = _build_dependency_graph(units, symbol_index)

    ordered: List[DiscoveredCodeUnit] = []
    visited: Set[str] = set()
    active_path: Set[str] = set()

    for unit in sorted(units, key=_stable_sort_key):
        _visit_unit(
            unit=unit,
            dependency_graph=dependency_graph,
            symbol_index=symbol_index,
            visited=visited,
            active_path=active_path,
            ordered=ordered,
        )

    return ordered


def _visit_unit(
    unit: DiscoveredCodeUnit,
    dependency_graph: Dict[str, List[str]],
    symbol_index: Dict[str, DiscoveredCodeUnit],
    visited: Set[str],
    active_path: Set[str],
    ordered: List[DiscoveredCodeUnit],
) -> None:
    if unit.qualified_name in visited:
        return

    if unit.qualified_name in active_path:
        return

    active_path.add(unit.qualified_name)

    for dependency_name in dependency_graph[unit.qualified_name]:
        dependency_unit = symbol_index.get(dependency_name)
        if dependency_unit is not None:
            _visit_unit(
                unit=dependency_unit,
                dependency_graph=dependency_graph,
                symbol_index=symbol_index,
                visited=visited,
                active_path=active_path,
                ordered=ordered,
            )

    active_path.remove(unit.qualified_name)
    visited.add(unit.qualified_name)
    ordered.append(unit)


def _build_symbol_index(units: List[DiscoveredCodeUnit]) -> Dict[str, DiscoveredCodeUnit]:
    """Build symbol index mapping both qualified names and bare symbol names.
    
    This allows dependency resolution when called_symbols contain simple names
    (e.g., "get_origin") while units are identified by qualified names 
    (e.g., "AuthorityRepository.get_origin").
    """
    index: Dict[str, DiscoveredCodeUnit] = {}
    for unit in units:
        index[unit.symbol] = unit
        # Also index by bare name (last component) for called_symbols matching
        bare_name = unit.symbol.split(".")[-1]
        if bare_name not in index:
            index[bare_name] = unit
    return index


def _build_dependency_graph(
    units: List[DiscoveredCodeUnit],
    symbol_index: Dict[str, DiscoveredCodeUnit],
) -> Dict[str, List[str]]:
    """Build dependency graph with intelligent same-class preference for collisions.
    
    For called_symbols that match multiple units (e.g., "process" could be 
    ClassA.process or ClassB.process), prefer the one in the same class as the caller.
    """
    graph: Dict[str, List[str]] = defaultdict(list)

    for unit in units:
        # Handle containment dependencies (children)
        for child_symbol in [*unit.methods, *unit.functions]:
            if child_symbol in symbol_index:
                graph[unit.qualified_name].append(child_symbol)
        
        # Handle call/reference dependencies with collision resolution
        for called_symbol in unit.called_symbols:
            if called_symbol in symbol_index:
                dependency_unit = symbol_index[called_symbol]
                
                # Check if there's a same-class version of this symbol
                # e.g., if caller is "ClassA.method" and called symbol is "helper",
                # prefer "ClassA.helper" over "OtherClass.helper"
                if "." in unit.symbol:
                    caller_class = unit.symbol.rsplit(".", 1)[0]
                    same_class_symbol = f"{caller_class}.{called_symbol}"
                    
                    # If the called symbol is already same-class, use it as-is
                    if dependency_unit.symbol == same_class_symbol:
                        graph[unit.qualified_name].append(dependency_unit.qualified_name)
                    # If not, check if there exists a same-class version
                    elif same_class_symbol in symbol_index:
                        same_class_unit = symbol_index[same_class_symbol]
                        graph[unit.qualified_name].append(same_class_unit.qualified_name)
                    # Otherwise use the bare-name match (could be different class)
                    else:
                        graph[unit.qualified_name].append(dependency_unit.qualified_name)
                else:
                    # Top-level function or method, use direct match
                    graph[unit.qualified_name].append(dependency_unit.qualified_name)

    return graph


def _stable_sort_key(unit: DiscoveredCodeUnit) -> tuple[str, int, str]:
    return (
        unit.path,
        unit.start_line or 0,
        unit.symbol,
    )
