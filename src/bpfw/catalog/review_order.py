
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

    for dependency_name in sorted(dependency_graph[unit.qualified_name]):
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
    return {unit.symbol: unit for unit in units}


def _build_dependency_graph(
    units: List[DiscoveredCodeUnit],
    symbol_index: Dict[str, DiscoveredCodeUnit],
) -> Dict[str, List[str]]:
    graph: Dict[str, List[str]] = defaultdict(list)

    for unit in units:
        for called_symbol in unit.called_symbols:
            if called_symbol in symbol_index:
                graph[unit.qualified_name].append(called_symbol)

    return graph


def _stable_sort_key(unit: DiscoveredCodeUnit) -> tuple[str, int, str]:
    return (
        unit.path,
        unit.start_line or 0,
        unit.symbol,
    )
