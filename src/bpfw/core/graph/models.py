"""System graph primitives used by impact and invariant analysis."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class GraphNode:
    identifier: str
    kind: str = "code"
    purpose: str | None = None
    domain: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    artifacts: tuple[str, ...] = ()
    intent_summary: str | None = None

@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    relationship: str = "depends_on"
    provenance: str = "declared"
    properties: dict[str, Any] = field(default_factory=dict)

@dataclass
class SystemGraph:
    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)

    def add_node(self, node: GraphNode) -> None:
        self.nodes[node.identifier] = node

    def add_edge(self, edge: GraphEdge) -> None:
        if edge.source not in self.nodes:
            self.add_node(GraphNode(identifier=edge.source, kind="unknown"))
        if edge.target not in self.nodes:
            self.add_node(GraphNode(identifier=edge.target, kind="unknown"))
        if edge not in self.edges:
            self.edges.append(edge)
