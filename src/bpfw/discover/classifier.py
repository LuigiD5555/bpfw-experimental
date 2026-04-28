"""Classification for discover findings."""

from __future__ import annotations

from dataclasses import dataclass

from bpfw.discover.scanner import DiscoverFinding


CATEGORY_BY_KIND: dict[str, str] = {
    "undeclared_file": "undeclared_file",
    "undeclared_symbol": "undeclared_symbol",
    "possible_duplicate": "possible_duplicate",
    "dependency_change": "dependency_change",
    "wiring_change": "wiring_change",
    "architecture_change": "architecture_change",
    "blueprint_change": "blueprint_change",
    "protection_change": "protection_change",
    "scanner_issue": "protection_change",
}

SEVERITY_BY_CATEGORY: dict[str, str] = {
    "undeclared_file": "medium",
    "undeclared_symbol": "medium",
    "possible_duplicate": "high",
    "dependency_change": "high",
    "wiring_change": "high",
    "architecture_change": "high",
    "blueprint_change": "critical",
    "protection_change": "critical",
}


@dataclass(slots=True)
class ClassifiedFinding:
    """Finding with normalized category and severity."""

    finding: DiscoverFinding
    category: str
    severity: str



def classify_findings(findings: list[DiscoverFinding]) -> list[ClassifiedFinding]:
    """Classify scanner findings into stable categories and severities."""

    classified: list[ClassifiedFinding] = []
    for finding in findings:
        category = CATEGORY_BY_KIND.get(finding.kind, "undeclared_symbol")
        severity = SEVERITY_BY_CATEGORY.get(category, "medium")
        classified.append(ClassifiedFinding(finding=finding, category=category, severity=severity))
    return classified
