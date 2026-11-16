"""Change impact and blast-radius calculation."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

from bpfw.core.graph.models import SystemGraph
from bpfw.core.graph.query import GraphQuery

@dataclass(frozen=True)
class ImpactResult:
    changed_components: tuple[str, ...]
    direct: tuple[str, ...]
    transitive: tuple[str, ...]
    systemic: bool
    critical_components: tuple[str, ...]

class ChangeImpactAnalyzer:
    def __init__(self, graph: SystemGraph) -> None:
        self.graph = graph
        self.query = GraphQuery(graph)

    def components_for_paths(self, changed_paths: list[str] | tuple[str, ...]) -> set[str]:
        normalized = {Path(path).as_posix() for path in changed_paths}
        components: set[str] = set()
        for node in self.graph.nodes.values():
            if any(Path(path).as_posix() in normalized for path in node.artifacts):
                components.add(node.identifier)
        return components

    def analyze_components(self, changed_components: set[str]) -> ImpactResult:
        direct: set[str] = set()
        transitive: set[str] = set()
        for component in changed_components:
            # Consumers are incoming dependencies; direct outgoing targets are also
            # relevant because a change can invalidate a dependency contract.
            direct.update(e.source for e in self.query.incoming(component))
            direct.update(e.target for e in self.query.outgoing(component))
            transitive.update(self.query.reachable(component, reverse=True))
            transitive.update(self.query.reachable(component, reverse=False))
        direct -= changed_components
        transitive -= changed_components
        transitive -= direct
        critical = tuple(sorted(
            node_id for node_id in changed_components | direct | transitive
            if bool(self.graph.nodes.get(node_id) and self.graph.nodes[node_id].properties.get("critical"))
        ))
        systemic = bool(critical) or len(changed_components | direct | transitive) >= max(5, len(self.graph.nodes) // 2)
        return ImpactResult(
            changed_components=tuple(sorted(changed_components)),
            direct=tuple(sorted(direct)),
            transitive=tuple(sorted(transitive)),
            systemic=systemic,
            critical_components=critical,
        )

    def analyze_paths(self, changed_paths: list[str] | tuple[str, ...]) -> ImpactResult:
        return self.analyze_components(self.components_for_paths(changed_paths))
