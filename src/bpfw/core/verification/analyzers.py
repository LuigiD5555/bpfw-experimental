"""Built-in system analyzers for intent, logic and interactions."""
from __future__ import annotations
from math import prod

from bpfw.core.graph.query import CONTROL_RELATIONSHIPS, GraphQuery
from bpfw.core.verification.context import VerificationContext
from bpfw.core.verification.invariants import InvariantEvaluator
from bpfw.reports.finding import Finding

class IntentCoverageAnalyzer:
    name = "intent_coverage"
    def analyze(self, context: VerificationContext) -> list[Finding]:
        if (context.blueprint.version or 1) < 2:
            return []
        findings: list[Finding] = []
        known = set(context.graph.nodes)
        for block in context.blueprint.blocks:
            if block.lifecycle == "active" and not (block.purpose or (block.intent and block.intent.summary)):
                findings.append(Finding(
                    source=self.name, code="INTENT_MISSING", severity="warning",
                    message=f"Active component '{block.identifier}' has no purpose or intent summary.",
                    category="intent_drift", affected_components=(block.identifier,), confidence="high",
                ))
            if block.intent:
                if block.intent.guarantees and not block.invariants:
                    findings.append(Finding(
                        source=self.name, code="INTENT_GUARANTEE_WITHOUT_INVARIANT", severity="warning",
                        message=f"Component '{block.identifier}' declares guarantees but no invariant protects them.",
                        evidence={"guarantees": block.intent.guarantees}, category="intent_drift",
                        affected_components=(block.identifier,), confidence="medium",
                    ))
            for invariant in block.invariants:
                subject = invariant.subject
                if subject and subject not in known and subject != block.identifier:
                    findings.append(Finding(
                        source=self.name, code="INVARIANT_UNKNOWN_SUBJECT", severity="warning",
                        message=f"Invariant '{invariant.identifier}' references unknown subject '{subject}'.",
                        affected_components=(block.identifier,), affected_invariants=(invariant.identifier,), confidence="high",
                    ))
        return findings

class DeclaredInvariantAnalyzer:
    name = "invariant_engine"
    def analyze(self, context: VerificationContext) -> list[Finding]:
        evaluator = InvariantEvaluator(context.graph)
        findings: list[Finding] = []
        for block in context.blueprint.blocks:
            for invariant in block.invariants:
                findings.extend(evaluator.evaluate(invariant, owner=block.identifier))
        project_invariants = context.raw_blueprint.get("invariants", [])
        if isinstance(project_invariants, list):
            from bpfw.core.catalog.domain.models import Invariant
            for raw in project_invariants:
                if isinstance(raw, dict):
                    invariant = Invariant.model_validate(raw)
                    findings.extend(evaluator.evaluate(invariant, owner=None))
        return findings

class ScalingBlindSpotAnalyzer:
    """Detect lower-capacity request-path components invisible to scaling controls."""
    name = "logical_relationships"
    OBSERVE = {"observes", "monitors", "scales_on"}

    def analyze(self, context: VerificationContext) -> list[Finding]:
        graph = context.graph
        query = GraphQuery(graph)
        findings: list[Finding] = []
        observers: dict[str, set[str]] = {}
        for edge in graph.edges:
            if edge.relationship in self.OBSERVE:
                observers.setdefault(edge.source, set()).add(edge.target)
        for controller, observed_targets in observers.items():
            for observed in observed_targets:
                observed_node = graph.nodes.get(observed)
                observed_capacity = _capacity(observed_node.properties if observed_node else {})
                if observed_capacity is None:
                    continue
                upstream = query.reachable(observed, reverse=True, include_control=False)
                for candidate in upstream:
                    if candidate == controller or candidate in observed_targets:
                        continue
                    node = graph.nodes.get(candidate)
                    if node is None:
                        continue
                    capacity = _capacity(node.properties)
                    if capacity is None or capacity >= observed_capacity:
                        continue
                    if candidate in observed_targets:
                        continue
                    path = query.shortest_path(candidate, observed)
                    findings.append(Finding(
                        source=self.name,
                        code="SCALING_BLIND_SPOT",
                        severity="block" if bool(node.properties.get("critical")) else "warning",
                        message=(
                            f"Component '{candidate}' has lower declared capacity ({capacity:g}) than observed component "
                            f"'{observed}' ({observed_capacity:g}), but scaling controller '{controller}' does not observe it."
                        ),
                        evidence={"controller": controller, "bottleneck": candidate, "observed": observed,
                                  "bottleneck_capacity": capacity, "observed_capacity": observed_capacity, "path": path},
                        category="logical_drift", affected_components=tuple(dict.fromkeys([controller, candidate, *path])),
                        confidence="high",
                    ))
        return _dedupe(findings)

class RetryAmplificationAnalyzer:
    name = "interaction_retry_amplification"

    def analyze(self, context: VerificationContext) -> list[Finding]:
        graph = context.graph
        retries = {node_id: _retry_attempts(node.properties) for node_id, node in graph.nodes.items()}
        retries = {node_id: value for node_id, value in retries.items() if value is not None and value > 1}
        maximum = context.blueprint.policy.max_retry_amplification or 8
        findings: list[Finding] = []
        for path in _request_paths(graph):
            retry_chain = [node for node in path if node in retries]
            if len(retry_chain) < 2:
                continue
            factors = [int(retries[node]) for node in retry_chain]
            amplification = prod(factors)
            if amplification <= maximum:
                continue
            findings.append(Finding(
                source=self.name, code="RETRY_AMPLIFICATION", severity="warning",
                message=f"Retry policies across {', '.join(retry_chain)} can amplify one operation to {amplification} attempts (budget {maximum}).",
                evidence={"path": path, "chain": retry_chain, "factors": factors, "amplification": amplification, "budget": maximum},
                category="interaction_drift", affected_components=tuple(retry_chain), confidence="high",
            ))
        return _dedupe(findings)


class NonIdempotentRetryAnalyzer:
    """Detect retries reaching a declared non-idempotent side effect."""
    name = "non_idempotent_retry"

    def analyze(self, context: VerificationContext) -> list[Finding]:
        findings: list[Finding] = []
        graph = context.graph
        for path in _request_paths(graph):
            if len(path) < 2:
                continue
            factors: list[int] = []
            retry_nodes: list[str] = []
            for node_id in path[:-1]:
                node = graph.nodes.get(node_id)
                attempts = _retry_attempts(node.properties if node else {})
                if attempts is not None and attempts > 1:
                    factors.append(int(attempts))
                    retry_nodes.append(node_id)
            if not factors:
                continue
            target_id = path[-1]
            target = graph.nodes.get(target_id)
            if target is None:
                continue
            props = target.properties
            non_idempotent = props.get("idempotent") is False or bool(props.get("non_idempotent"))
            side_effect = bool(props.get("side_effect")) or non_idempotent
            if not side_effect or not non_idempotent:
                continue
            attempts = prod(factors)
            findings.append(Finding(
                source=self.name, code="NON_IDEMPOTENT_RETRY_RISK",
                severity="block" if bool(props.get("critical")) else "warning",
                message=(
                    f"Retries on {', '.join(retry_nodes)} can execute non-idempotent side effect "
                    f"'{target_id}' up to {attempts} times for one initiating operation."
                ),
                evidence={"path": path, "retry_nodes": retry_nodes, "possible_attempts": attempts, "target": target_id},
                category="logical_drift", affected_components=tuple(path), confidence="high",
            ))
        return _dedupe(findings)


class FailoverCapacityAnalyzer:
    name = "failover_capacity"
    FAILOVER = {"failover_to", "redirects_to_on_failure", "backup_region"}
    def analyze(self, context: VerificationContext) -> list[Finding]:
        findings: list[Finding] = []
        for edge in context.graph.edges:
            if edge.relationship not in self.FAILOVER:
                continue
            source = context.graph.nodes.get(edge.source)
            target = context.graph.nodes.get(edge.target)
            if source is None or target is None:
                continue
            source_load = _load(source.properties)
            target_load = _load(target.properties)
            capacity = _capacity(target.properties)
            amplification = float(edge.properties.get("amplification", 1) or 1)
            if None in {source_load, target_load, capacity}:
                continue
            required = float(target_load) + float(source_load) * amplification
            if float(capacity) >= required:
                continue
            findings.append(Finding(
                source=self.name, code="FAILOVER_CAPACITY_VIOLATION", severity="block",
                message=f"Failover from '{edge.source}' to '{edge.target}' requires {required:g} capacity but only {float(capacity):g} is declared.",
                evidence={"source_load": source_load, "target_load": target_load, "amplification": amplification,
                          "required": required, "capacity": capacity},
                category="interaction_drift", affected_components=(edge.source, edge.target), confidence="high",
            ))
        return findings

class InteractionStateAnalyzer:
    """Detect incompatible simultaneous proposed/system states."""
    name = "interaction_state"
    def analyze(self, context: VerificationContext) -> list[Finding]:
        findings: list[Finding] = []
        groups = context.raw_blueprint.get("interaction_constraints", [])
        if not isinstance(groups, list):
            return findings
        for item in groups:
            if not isinstance(item, dict):
                continue
            forbidden = item.get("not_simultaneous", [])
            if not isinstance(forbidden, list):
                continue
            active: list[str] = []
            for requirement in forbidden:
                if not isinstance(requirement, dict):
                    continue
                component = str(requirement.get("component") or "")
                state = requirement.get("state")
                node = context.graph.nodes.get(component)
                if node and node.properties.get("state") == state:
                    active.append(component)
            if len(active) == len(forbidden) and active:
                findings.append(Finding(
                    source=self.name, code="INCOMPATIBLE_SIMULTANEOUS_STATE", severity=str(item.get("severity", "block")),
                    message=str(item.get("description") or "Individually valid states are unsafe when active together."),
                    evidence={"active": active}, category="interaction_drift",
                    affected_components=tuple(active), confidence="high",
                ))
        return findings


def _request_paths(graph, max_depth: int = 24):  # noqa: ANN001, ANN202
    """Yield technology-agnostic simple data/request paths without control edges."""
    outgoing = {}
    incoming_count = {node_id: 0 for node_id in graph.nodes}
    for edge in graph.edges:
        if edge.relationship in CONTROL_RELATIONSHIPS:
            continue
        outgoing.setdefault(edge.source, []).append(edge.target)
        incoming_count[edge.target] = incoming_count.get(edge.target, 0) + 1
    roots = [node_id for node_id in graph.nodes if incoming_count.get(node_id, 0) == 0]
    if not roots:
        roots = list(graph.nodes)
    yielded = set()
    for root in roots:
        stack = [(root, [root])]
        while stack:
            current, path = stack.pop()
            targets = [target for target in outgoing.get(current, []) if target not in path]
            if not targets or len(path) >= max_depth:
                key = tuple(path)
                if len(path) > 1 and key not in yielded:
                    yielded.add(key)
                    yield path
                continue
            for target in targets:
                stack.append((target, [*path, target]))


def _capacity(properties):  # noqa: ANN001, ANN202
    value = properties.get("capacity")
    if isinstance(value, dict):
        value = value.get("max", value.get("effective"))
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

def _load(properties):  # noqa: ANN001, ANN202
    value = properties.get("load", properties.get("baseline_load"))
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

def _retry_attempts(properties):  # noqa: ANN001, ANN202
    for key in ("retry", "retries"):
        value = properties.get(key)
        if isinstance(value, dict):
            attempts = value.get("max_attempts", value.get("attempts"))
            if isinstance(attempts, (int, float)):
                return int(attempts)
        if isinstance(value, (int, float)):
            return int(value)
    attempts = properties.get("max_attempts")
    return int(attempts) if isinstance(attempts, (int, float)) else None

def _dedupe(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple[str, tuple[str, ...]]] = set()
    result: list[Finding] = []
    for finding in findings:
        key = (finding.code, finding.affected_components)
        if key in seen:
            continue
        seen.add(key)
        result.append(finding)
    return result
