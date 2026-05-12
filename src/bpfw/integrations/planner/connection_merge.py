"""Merge hybrid connections from blueprint and inferred sources."""

from typing import Dict, List, Tuple

from bpfw.integrations.planner.connection_detection import InferredConnection
from bpfw.integrations.planner.models import PlannerConnection


def merge_connections(
    blueprint_connections: List[PlannerConnection],
    inferred_connections: List[InferredConnection],
) -> List[PlannerConnection]:
    """Merge connections with blueprint precedence and inferred suggestions."""

    merged: List[PlannerConnection] = []
    by_pair: Dict[Tuple[str, str], List[PlannerConnection]] = {}
    accepted_keys = set()

    for connection in blueprint_connections:
        normalized = PlannerConnection(
            source_box_id=connection.source_box_id,
            target_box_id=connection.target_box_id,
            relationship=connection.relationship,
            source_kind="blueprint",
            confidence=connection.confidence or "high",
            evidence=connection.evidence or ["declared:connections"],
            status="accepted",
            notes=connection.notes,
        )
        merged.append(normalized)
        by_pair.setdefault((normalized.source_box_id, normalized.target_box_id), []).append(normalized)
        accepted_keys.add((normalized.source_box_id, normalized.target_box_id, normalized.relationship))

    for inferred in inferred_connections:
        key = (inferred.source_box_id, inferred.target_box_id, inferred.relationship)
        if key in accepted_keys:
            continue

        # If pair exists with different relationship, blueprint has precedence.
        same_pair = by_pair.get((inferred.source_box_id, inferred.target_box_id), [])
        if same_pair:
            continue

        merged.append(
            PlannerConnection(
                source_box_id=inferred.source_box_id,
                target_box_id=inferred.target_box_id,
                relationship=inferred.relationship,
                source_kind="inferred",
                confidence=inferred.confidence,
                evidence=list(inferred.evidence),
                status="suggested",
            )
        )

    return merged
