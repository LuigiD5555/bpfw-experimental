"""Build the declared + detected BPFW System Graph."""
from __future__ import annotations
from pathlib import Path
from typing import Any

from bpfw.core.catalog.domain.models import BlueprintDocument
from bpfw.core.catalog.models import ScanResult
from bpfw.core.graph.models import GraphEdge, GraphNode, SystemGraph

class SystemGraphBuilder:
    def build(
        self,
        document: BlueprintDocument,
        *,
        scan_result: ScanResult | None = None,
        project_root: Path | None = None,
    ) -> SystemGraph:
        graph = SystemGraph()
        block_by_code_key: dict[tuple[str, str], str] = {}
        block_by_symbol: dict[str, list[str]] = {}

        for block in document.blocks:
            extra = dict(block.model_extra or {})
            properties: dict[str, Any] = dict(block.properties)
            for key in (
                "capacity", "load", "baseline_load", "retry", "retries",
                "max_attempts", "critical", "availability", "state", "role",
            ):
                if key in extra and key not in properties:
                    properties[key] = extra[key]
            artifact_paths = tuple(a.path for a in block.all_artifacts() if a.path)
            graph.add_node(
                GraphNode(
                    identifier=block.identifier,
                    kind=block.kind,
                    purpose=block.purpose,
                    domain=block.domain,
                    properties=properties,
                    artifacts=artifact_paths,
                    intent_summary=block.intent.summary if block.intent else None,
                )
            )
            if block.location.path and block.location.symbol:
                block_by_code_key[(block.location.path, block.location.symbol)] = block.identifier
                leaf = block.location.symbol.rsplit(".", 1)[-1]
                block_by_symbol.setdefault(leaf, []).append(block.identifier)
            for artifact in block.artifacts:
                if artifact.type == "code" and artifact.path and artifact.symbol:
                    block_by_code_key[(artifact.path, artifact.symbol)] = block.identifier
                    block_by_symbol.setdefault(artifact.symbol.rsplit(".", 1)[-1], []).append(block.identifier)

        for block in document.blocks:
            for connection in block.connections:
                if not connection.target:
                    continue
                graph.add_edge(
                    GraphEdge(
                        source=block.identifier,
                        target=connection.target,
                        relationship=connection.relationship or connection.meaning or "depends_on",
                        provenance=connection.provenance or "declared",
                        properties=dict(connection.properties),
                    )
                )

        if scan_result is not None:
            for unit in scan_result.discovered_units:
                source_id = block_by_code_key.get((unit.path, unit.symbol))
                if source_id is None:
                    continue
                for call in unit.calls:
                    if not isinstance(call, dict):
                        continue
                    name = call.get("name")
                    if not isinstance(name, str) or not name:
                        continue
                    candidates = block_by_symbol.get(name.rsplit(".", 1)[-1], [])
                    if len(candidates) == 1 and candidates[0] != source_id:
                        graph.add_edge(
                            GraphEdge(
                                source=source_id,
                                target=candidates[0],
                                relationship="calls",
                                provenance="detected",
                                properties={"source": "python_ast"},
                            )
                        )
        return graph
