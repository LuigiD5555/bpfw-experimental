"""Safe, fail-closed invariant evaluation over the System Graph."""
from __future__ import annotations

from math import prod
from typing import Any

from bpfw.core.catalog.domain.models import Invariant
from bpfw.core.graph.models import SystemGraph
from bpfw.core.graph.query import GraphQuery
from bpfw.reports.finding import Finding


class InvariantConfigurationError(ValueError):
    """Raised when a declared invariant cannot be evaluated deterministically."""


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _required_number(value: Any, label: str) -> float:
    number = _number(value)
    if number is None:
        raise InvariantConfigurationError(f"{label} must be a finite numeric value.")
    if number != number or number in {float("inf"), float("-inf")}:
        raise InvariantConfigurationError(f"{label} must be a finite numeric value.")
    return number


def _required_int(value: Any, label: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvariantConfigurationError(f"{label} must be an integer.")
    if minimum is not None and value < minimum:
        raise InvariantConfigurationError(f"{label} must be >= {minimum}.")
    return value


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvariantConfigurationError(f"{label} must be a non-empty string.")
    return value.strip()


def _severity(value: str) -> str:
    normalized = value.lower()
    if normalized in {"block", "error", "critical"}:
        return "block"
    if normalized in {"warning", "warn"}:
        return "warning"
    return "info"


class InvariantEvaluator:
    """Evaluate structured invariants without eval/exec.

    Unsupported or malformed declared invariants never disappear silently.  A
    structured finding is emitted instead, so a safety rule cannot become an
    accidental PASS merely because BPFW could not interpret it.
    """

    def __init__(self, graph: SystemGraph) -> None:
        self.graph = graph
        self.query = GraphQuery(graph)

    def evaluate(self, invariant: Invariant, owner: str | None = None) -> list[Finding]:
        assertion = invariant.assertion or {}
        invariant_type = invariant.type.strip().lower().replace(" ", "_")

        # custom_evidence is intentionally evaluated by the Evidence Engine.
        if invariant_type == "custom_evidence":
            return []

        handler = getattr(self, f"_eval_{invariant_type}", None)
        if handler is None:
            return [self._configuration_finding(
                invariant,
                invariant_type,
                f"Unsupported invariant type '{invariant_type or '<empty>'}'.",
                owner,
                code="INVARIANT_UNSUPPORTED_TYPE",
            )]
        try:
            ok, evidence, components = handler(assertion, owner)
        except (InvariantConfigurationError, TypeError, ValueError, OverflowError) as error:
            return [self._configuration_finding(
                invariant,
                invariant_type,
                str(error),
                owner,
                code="INVARIANT_CONFIGURATION_ERROR",
            )]

        if ok:
            return []
        return [Finding(
            source="invariant_engine",
            code="INVARIANT_VIOLATION",
            severity=_severity(invariant.severity),
            message=invariant.description or f"Invariant '{invariant.identifier}' is violated.",
            evidence={"invariant": invariant.identifier, "type": invariant_type, **evidence},
            category="logical_drift",
            affected_components=tuple(sorted({component for component in components if component})),
            affected_invariants=(invariant.identifier,),
            confidence="high",
        )]

    def _configuration_finding(
        self,
        invariant: Invariant,
        invariant_type: str,
        reason: str,
        owner: str | None,
        *,
        code: str,
    ) -> Finding:
        return Finding(
            source="invariant_engine",
            code=code,
            severity=_severity(invariant.severity),
            message=(
                f"Invariant '{invariant.identifier or '<unnamed>'}' could not be evaluated: {reason}"
            ),
            evidence={
                "invariant": invariant.identifier,
                "type": invariant_type,
                "reason": reason,
            },
            category="logical_drift",
            affected_components=(owner,) if owner else (),
            affected_invariants=(invariant.identifier,) if invariant.identifier else (),
            confidence="high",
        )

    def _relation_args(self, assertion: dict[str, Any], owner: str | None) -> tuple[str, str, str | None]:
        source = _required_text(assertion.get("source") or owner, "source")
        target = _required_text(assertion.get("target"), "target")
        relationship = assertion.get("relationship")
        if relationship is not None:
            relationship = _required_text(relationship, "relationship")
        return source, target, relationship

    def _eval_requires_relation(self, assertion, owner):  # noqa: ANN001, ANN202
        source, target, relationship = self._relation_args(assertion, owner)
        edges = self.query.outgoing(source, {relationship} if relationship else None)
        ok = any(e.target == target for e in edges)
        return ok, {"source": source, "target": target, "relationship": relationship}, [source, target]

    def _eval_forbids_relation(self, assertion, owner):  # noqa: ANN001, ANN202
        source, target, relationship = self._relation_args(assertion, owner)
        edges = self.query.outgoing(source, {relationship} if relationship else None)
        ok = not any(e.target == target for e in edges)
        return ok, {"source": source, "target": target, "relationship": relationship}, [source, target]

    def _eval_requires_path(self, assertion, owner):  # noqa: ANN001, ANN202
        source, target, relationship = self._relation_args(assertion, owner)
        ok = self.query.path_exists(source, target, relationship)
        return ok, {"source": source, "target": target, "relationship": relationship}, [source, target]

    def _eval_forbids_path(self, assertion, owner):  # noqa: ANN001, ANN202
        source, target, relationship = self._relation_args(assertion, owner)
        ok = not self.query.path_exists(source, target, relationship)
        return ok, {"source": source, "target": target, "relationship": relationship}, [source, target]

    def _eval_max_cardinality(self, assertion, owner):  # noqa: ANN001, ANN202
        source = _required_text(assertion.get("source") or owner, "source")
        relationship = assertion.get("relationship")
        if relationship is not None:
            relationship = _required_text(relationship, "relationship")
        maximum = _required_int(assertion.get("max", assertion.get("value", 1)), "max", minimum=0)
        count = len(self.query.outgoing(source, {relationship} if relationship else None))
        return count <= maximum, {"source": source, "actual": count, "max": maximum}, [source]

    def _eval_min_cardinality(self, assertion, owner):  # noqa: ANN001, ANN202
        source = _required_text(assertion.get("source") or owner, "source")
        relationship = assertion.get("relationship")
        if relationship is not None:
            relationship = _required_text(relationship, "relationship")
        minimum = _required_int(assertion.get("min", assertion.get("value", 1)), "min", minimum=0)
        count = len(self.query.outgoing(source, {relationship} if relationship else None))
        return count >= minimum, {"source": source, "actual": count, "min": minimum}, [source]

    def _property_value(self, component: str, field: str) -> Any:
        node = self.graph.nodes.get(component)
        if node is None:
            return None
        value: Any = node.properties
        for part in field.split("."):
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value

    def _numeric_property(self, component: str, field: str) -> float:
        if component not in self.graph.nodes:
            raise InvariantConfigurationError(f"component '{component}' does not exist in the System Graph.")
        value = self._property_value(component, field)
        return _required_number(value, f"property '{component}.{field}'")

    def _eval_value_less_than(self, assertion, owner):  # noqa: ANN001, ANN202
        component = _required_text(assertion.get("component") or owner, "component")
        field = _required_text(assertion.get("field") or "value", "field")
        actual = self._numeric_property(component, field)
        maximum = _required_number(assertion.get("max", assertion.get("value")), "max")
        return actual < maximum, {"component": component, "field": field, "actual": actual, "max": maximum}, [component]

    def _eval_value_greater_than(self, assertion, owner):  # noqa: ANN001, ANN202
        component = _required_text(assertion.get("component") or owner, "component")
        field = _required_text(assertion.get("field") or "value", "field")
        actual = self._numeric_property(component, field)
        minimum = _required_number(assertion.get("min", assertion.get("value")), "min")
        return actual > minimum, {"component": component, "field": field, "actual": actual, "min": minimum}, [component]

    def _eval_capacity_margin(self, assertion, owner):  # noqa: ANN001, ANN202
        component = _required_text(assertion.get("component") or owner, "component")
        capacity_value = assertion.get("capacity")
        capacity = (
            _required_number(capacity_value, "capacity")
            if capacity_value is not None
            else self._numeric_property(component, _required_text(assertion.get("capacity_field", "capacity"), "capacity_field"))
        )
        demand_value = assertion.get("demand")
        demand = (
            _required_number(demand_value, "demand")
            if demand_value is not None
            else self._numeric_property(component, _required_text(assertion.get("demand_field", "load"), "demand_field"))
        )
        margin = _required_number(assertion.get("margin", 0), "margin")
        if margin < 0:
            raise InvariantConfigurationError("margin must be >= 0.")
        ok = capacity >= demand * (1 + margin)
        return ok, {"component": component, "capacity": capacity, "demand": demand, "margin": margin}, [component]

    def _eval_bounded_amplification(self, assertion, owner):  # noqa: ANN001, ANN202
        factors = assertion.get("factors")
        if not isinstance(factors, list) or not factors:
            raise InvariantConfigurationError("factors must be a non-empty list.")
        values: list[float] = []
        components: list[str] = []
        for index, item in enumerate(factors):
            if isinstance(item, bool):
                raise InvariantConfigurationError(f"factors[{index}] must be numeric or a component property reference.")
            if isinstance(item, (int, float)):
                value = _required_number(item, f"factors[{index}]")
                if value <= 0:
                    raise InvariantConfigurationError(f"factors[{index}] must be > 0.")
                values.append(value)
                continue
            if isinstance(item, dict):
                component = _required_text(item.get("component") or owner, f"factors[{index}].component")
                field = _required_text(item.get("field") or "retry.max_attempts", f"factors[{index}].field")
                value = self._numeric_property(component, field)
                if value <= 0:
                    raise InvariantConfigurationError(f"property '{component}.{field}' must be > 0.")
                values.append(value)
                components.append(component)
                continue
            raise InvariantConfigurationError(f"factors[{index}] must be numeric or a component property reference.")
        actual = prod(values)
        maximum = _required_number(assertion.get("max", 1), "max")
        if maximum <= 0:
            raise InvariantConfigurationError("max must be > 0.")
        return actual <= maximum, {"actual_amplification": actual, "max": maximum, "factors": values}, components

    def _eval_amplification(self, assertion, owner):  # noqa: ANN001, ANN202
        return self._eval_bounded_amplification(assertion, owner)

    def _eval_compatibility(self, assertion, owner):  # noqa: ANN001, ANN202
        required = assertion.get("requires")
        if not isinstance(required, dict) or not required:
            raise InvariantConfigurationError("requires must be a non-empty mapping of component to expected state.")
        components: list[str] = []
        failures: dict[str, Any] = {}
        for component, expected in required.items():
            component_id = _required_text(component, "requires component")
            components.append(component_id)
            actual = self.graph.nodes.get(component_id)
            state = actual.properties.get("state") if actual else None
            if state != expected:
                failures[component_id] = {"expected": expected, "actual": state}
        return not failures, {"failures": failures}, components

    def _eval_mutual_exclusion(self, assertion, owner):  # noqa: ANN001, ANN202
        states = assertion.get("states")
        if not isinstance(states, list) or not states:
            raise InvariantConfigurationError("states must be a non-empty list.")
        active: list[str] = []
        components: list[str] = []
        for index, item in enumerate(states):
            if not isinstance(item, dict):
                raise InvariantConfigurationError(f"states[{index}] must be a mapping.")
            component = _required_text(item.get("component"), f"states[{index}].component")
            if "state" not in item:
                raise InvariantConfigurationError(f"states[{index}].state is required.")
            forbidden_state = item.get("state")
            components.append(component)
            node = self.graph.nodes.get(component)
            if node and node.properties.get("state") == forbidden_state:
                active.append(component)
        maximum = _required_int(assertion.get("max_active", 1), "max_active", minimum=0)
        return len(active) <= maximum, {"active": active, "max_active": maximum}, components
