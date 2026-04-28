"""Risk scoring for discover findings."""

from __future__ import annotations

from bpfw.discover.classifier import ClassifiedFinding


RISK_ORDER: dict[str, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}



def risk_for_finding(classified_finding: ClassifiedFinding) -> str:
    """Return risk level for one classified finding."""

    category = classified_finding.category
    file_path = classified_finding.finding.file_path

    if category in {"blueprint_change", "protection_change"}:
        return "critical"
    if category in {"dependency_change", "wiring_change", "architecture_change", "possible_duplicate"}:
        return "high"
    if category == "undeclared_file":
        if file_path.startswith("tests/"):
            return "low"
        return "medium"
    if category == "undeclared_symbol":
        return "medium"
    return "medium"



def aggregate_risk(levels: list[str]) -> str:
    """Aggregate highest risk from a list."""

    if not levels:
        return "low"
    return max(levels, key=lambda level: RISK_ORDER.get(level, 1))
