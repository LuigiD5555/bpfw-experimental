"""Indexes for fast graph lookup."""
from __future__ import annotations
from dataclasses import dataclass
from bpfw.core.graph.models import SystemGraph

@dataclass
class GraphIndex:
    graph: SystemGraph

    def by_kind(self, kind: str):  # noqa: ANN201
        return [node for node in self.graph.nodes.values() if node.kind == kind]

    def by_artifact(self, path: str):  # noqa: ANN201
        return [node for node in self.graph.nodes.values() if path in node.artifacts]
