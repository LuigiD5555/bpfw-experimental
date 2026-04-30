"""Catalog Mode verify logic for BPFW MVP."""

from dataclasses import dataclass, field
from pathlib import Path

from bpfw.blueprint.models import BlueprintModel
from bpfw.init.scanner import MechanicalProjectScanner

ALLOWED_LIFECYCLES = {"active", "experimental", "legacy", "deprecated"}


@dataclass(slots=True)
class CatalogFinding:
    """Single verify finding."""

    code: str
    status: str
    message: str
    resource: str


@dataclass(slots=True)
class CatalogVerifyResult:
    """Catalog verify output."""

    status: str
    findings: list[CatalogFinding] = field(default_factory=list)
    summary: dict[str, str] = field(default_factory=dict)


def _build_discovered_units(project_root: Path) -> set[str]:
    scanner = MechanicalProjectScanner()
    scan_result = scanner.scan(project_root=project_root)
    discovered_units: set[str] = set()
    for symbol in scan_result.symbols:
        if symbol.kind in {"class", "function"}:
            discovered_units.add(f"{symbol.file_path}::{symbol.name}")
    return discovered_units


def run_catalog_verify(project_root: Path, blueprint: BlueprintModel) -> CatalogVerifyResult:
    """Run catalog scanner, drift and lifecycle checks."""

    findings: list[CatalogFinding] = []
    declared_units: set[str] = set()
    duplicate_active_intents: dict[str, list[str]] = {}
    invalid_lifecycles = 0

    for responsibility in blueprint.responsibilities:
        lifecycle_state = (responsibility.lifecycle_state or "").strip().lower()
        if lifecycle_state not in ALLOWED_LIFECYCLES:
            invalid_lifecycles += 1
            findings.append(
                CatalogFinding(
                    code="INVALID_LIFECYCLE",
                    status="block",
                    message=(
                        f"Responsibility `{responsibility.responsibility_id}` has invalid lifecycle_state "
                        f"`{responsibility.lifecycle_state}`"
                    ),
                    resource=str(blueprint.source_path or "bpfw/blueprint.yaml"),
                )
            )

        intent_text = (responsibility.intent or "").strip().lower()
        if lifecycle_state == "active" and intent_text:
            duplicate_active_intents.setdefault(intent_text, []).append(responsibility.responsibility_id)

        allowed_files = set(responsibility.allowed_files)
        active_implementation_id = responsibility.active_implementation
        active_implementation = next(
            (item for item in responsibility.allowed_implementations if item.implementation_id == active_implementation_id),
            None,
        )

        for symbol_name in responsibility.allowed_symbols:
            if "." in symbol_name:
                continue
            for allowed_file in allowed_files:
                declared_units.add(f"{allowed_file}::{symbol_name}")

        if active_implementation is not None and active_implementation.class_name:
            declared_units.add(f"{active_implementation.file}::{active_implementation.class_name}")

    for intent_text, responsibility_ids in sorted(duplicate_active_intents.items()):
        if len(responsibility_ids) > 1:
            findings.append(
                CatalogFinding(
                    code="DUPLICATE_ACTIVE_INTENT",
                    status="block",
                    message=(
                        f"intent `{intent_text}` has multiple active responsibilities: "
                        + ", ".join(sorted(responsibility_ids))
                    ),
                    resource=str(blueprint.source_path or "bpfw/blueprint.yaml"),
                )
            )

    discovered_units = _build_discovered_units(project_root=project_root)

    missing_declared_units = sorted(declared_units - discovered_units)
    undeclared_units = sorted(discovered_units - declared_units)

    for missing_unit in missing_declared_units:
        findings.append(
            CatalogFinding(
                code="MISSING_DECLARED_CODE",
                status="block",
                message=f"Declared code unit is missing in project: {missing_unit}",
                resource=missing_unit,
            )
        )

    for undeclared_unit in undeclared_units:
        findings.append(
            CatalogFinding(
                code="UNDECLARED_CODE",
                status="block",
                message=f"Code unit exists but is not declared in blueprint: {undeclared_unit}",
                resource=undeclared_unit,
            )
        )

    blocked_findings = [item for item in findings if item.status == "block"]
    status = "block" if blocked_findings else "ok"

    return CatalogVerifyResult(
        status=status,
        findings=findings,
        summary={
            "declared_units": str(len(declared_units)),
            "discovered_units": str(len(discovered_units)),
            "missing_declared_code": str(len(missing_declared_units)),
            "undeclared_code": str(len(undeclared_units)),
            "duplicate_active_intents": str(
                len([intent for intent, responsibility_ids in duplicate_active_intents.items() if len(responsibility_ids) > 1])
            ),
            "invalid_lifecycles": str(invalid_lifecycles),
        },
    )
