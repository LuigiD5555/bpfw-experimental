"""Traversal helpers for the BPFW System Graph."""
from __future__ import annotations
from collections import deque
from bpfw.core.graph.models import GraphEdge, SystemGraph

CONTROL_RELATIONSHIPS = {"observes", "monitors", "scales_on", "governed_by", "policy_for"}

class GraphQuery:
    def __init__(self, graph: SystemGraph) -> None:
        self.graph = graph

    def outgoing(self, node_id: str, relationships: set[str] | None = None) -> list[GraphEdge]:
        return [e for e in self.graph.edges if e.source == node_id and (relationships is None or e.relationship in relationships)]

    def incoming(self, node_id: str, relationships: set[str] | None = None) -> list[GraphEdge]:
        return [e for e in self.graph.edges if e.target == node_id and (relationships is None or e.relationship in relationships)]

    def reachable(
        self,
        node_id: str,
        *,
        reverse: bool = False,
        include_control: bool = True,
        max_depth: int | None = None,
    ) -> set[str]:
        seen: set[str] = set()
        queue = deque([(node_id, 0)])
        while queue:
            current, depth = queue.popleft()
            if max_depth is not None and depth >= max_depth:
                continue
            edges = self.incoming(current) if reverse else self.outgoing(current)
            for edge in edges:
                if not include_control and edge.relationship in CONTROL_RELATIONSHIPS:
                    continue
                nxt = edge.source if reverse else edge.target
                if nxt in seen or nxt == node_id:
                    continue
                seen.add(nxt)
                queue.append((nxt, depth + 1))
        return seen

    def path_exists(self, source: str, target: str, relationship: str | None = None) -> bool:
        if source == target:
            return True
        allowed = {relationship} if relationship else None
        seen = {source}
        queue = deque([source])
        while queue:
            current = queue.popleft()
            for edge in self.outgoing(current, allowed):
                if edge.target == target:
                    return True
                if edge.target not in seen:
                    seen.add(edge.target)
                    queue.append(edge.target)
        return False

    def shortest_path(self, source: str, target: str) -> list[str]:
        if source == target:
            return [source]
        queue = deque([(source, [source])])
        seen = {source}
        while queue:
            current, path = queue.popleft()
            for edge in self.outgoing(current):
                if edge.target == target:
                    return [*path, target]
                if edge.target not in seen:
                    seen.add(edge.target)
                    queue.append((edge.target, [*path, edge.target]))
        return []
