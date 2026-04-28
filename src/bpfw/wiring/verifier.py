"""Wiring verifier for Blueprint active implementation alignment."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bpfw.blueprint.models import BlueprintImplementation, BlueprintResponsibility
from bpfw.blueprint.validator import validate_blueprint
from bpfw.runtime.collector import collect_runtime_snapshot
from bpfw.runtime.contract import RuntimeBinding
from bpfw.wiring.composition_root import validate_runtime_source


@dataclass(slots=True)
class WiringIssue:
    """Deterministic wiring verification issue."""

    severity: str
    code: str
    message: str
    file_path: str
    recommendation: str


@dataclass(slots=True)
class WiringVerificationResult:
    """Output contract for wiring verification."""

    issues: list[WiringIssue] = field(default_factory=list)
    active_bindings: list[RuntimeBinding] = field(default_factory=list)



def _make_issue(
    severity: str,
    code: str,
    message: str,
    file_path: Path,
    recommendation: str,
) -> WiringIssue:
    return WiringIssue(
        severity=severity,
        code=code,
        message=message,
        file_path=str(file_path),
        recommendation=recommendation,
    )



def _implementation_index(
    responsibility: BlueprintResponsibility,
) -> dict[str, BlueprintImplementation]:
    return {
        implementation.implementation_id: implementation
        for implementation in responsibility.allowed_implementations
    }


def _issue_priority(issue: WiringIssue) -> tuple[int, int]:
    severity_priority = {
        "critical": 0,
        "block": 1,
        "warning": 2,
    }
    code_priority = {
        "WR008": 0,  # disabled running
        "WR006": 1,  # unknown implementation
        "WR007": 2,  # experimental runtime
        "WR010": 3,  # deprecated runtime
        "WR004": 4,  # missing runtime binding
        "WR005": 5,  # drift
        "WR009": 6,  # source authorization
        "WR003": 7,
        "WR002": 8,
        "WR001": 9,
    }
    return severity_priority.get(issue.severity, 9), code_priority.get(issue.code, 99)



def verify_wiring(project_root: Path) -> WiringVerificationResult:
    """Compare blueprint active implementation against runtime active bindings."""

    validation_result = validate_blueprint(project_root=project_root)
    if not validation_result.is_valid or validation_result.blueprint is None:
        first_error = validation_result.errors[0]
        return WiringVerificationResult(
            issues=[
                _make_issue(
                    severity="block",
                    code="WR001",
                    message=f"Blueprint must be valid before wiring verification: {first_error.message}",
                    file_path=Path(first_error.file_path),
                    recommendation=first_error.recommendation,
                )
            ]
        )

    runtime_result = collect_runtime_snapshot(project_root=project_root)
    if runtime_result.errors:
        first_runtime_error = runtime_result.errors[0]
        return WiringVerificationResult(
            issues=[
                _make_issue(
                    severity="block",
                    code="WR002",
                    message=f"Runtime snapshot collection failed: {first_runtime_error.message}",
                    file_path=Path(first_runtime_error.file_path),
                    recommendation=first_runtime_error.recommendation,
                )
            ]
        )

    snapshot = runtime_result.snapshot
    if snapshot is None:
        return WiringVerificationResult(
            issues=[
                _make_issue(
                    severity="block",
                    code="WR003",
                    message="Runtime snapshot is unavailable",
                    file_path=project_root / ".bpfw/runtime_bindings.yaml",
                    recommendation="Declare active runtime bindings metadata",
                )
            ]
        )

    issues: list[WiringIssue] = []
    bindings_by_responsibility = {
        binding.responsibility_id: binding for binding in snapshot.active_bindings
    }

    for responsibility in validation_result.blueprint.responsibilities:
        if responsibility.lifecycle_state != "active":
            continue
        binding = bindings_by_responsibility.get(responsibility.responsibility_id)
        if binding is None:
            issues.append(
                _make_issue(
                    severity="block",
                    code="WR004",
                    message=(
                        f"Missing runtime binding for responsibility "
                        f"`{responsibility.responsibility_id}`"
                    ),
                    file_path=project_root / ".bpfw/runtime_bindings.yaml",
                    recommendation="Declare runtime_implementation for all active responsibilities",
                )
            )
            continue

        runtime_implementation_identifier = (binding.runtime_implementation or "").strip()
        if not runtime_implementation_identifier:
            issues.append(
                _make_issue(
                    severity="block",
                    code="WR004",
                    message=(
                        f"Missing runtime implementation for responsibility "
                        f"`{responsibility.responsibility_id}`"
                    ),
                    file_path=project_root / ".bpfw/runtime_bindings.yaml",
                    recommendation="Declare runtime_implementation for all active responsibilities",
                )
            )
            continue

        source_check = validate_runtime_source(project_root=project_root, source=binding.source)
        if not source_check.is_authorized:
            issues.append(
                _make_issue(
                    severity="block",
                    code="WR009",
                    message=(
                        f"Runtime binding source is not an authorized composition root for "
                        f"`{responsibility.responsibility_id}`: {binding.source}"
                    ),
                    file_path=Path(source_check.resolved_source or binding.source),
                    recommendation="Move runtime wiring source to declared composition roots",
                )
            )

        implementation_by_identifier = _implementation_index(responsibility)
        runtime_implementation = implementation_by_identifier.get(runtime_implementation_identifier)
        if runtime_implementation is None:
            issues.append(
                _make_issue(
                    severity="block",
                    code="WR006",
                    message=(
                        f"Runtime uses undeclared implementation `{runtime_implementation_identifier}` "
                        f"for responsibility `{responsibility.responsibility_id}`"
                    ),
                    file_path=project_root / ".bpfw/runtime_bindings.yaml",
                    recommendation="Use only implementation_id values declared in blueprint allowed_implementations",
                )
            )
            continue

        runtime_state = runtime_implementation.lifecycle_state
        if runtime_state == "experimental":
            issues.append(
                _make_issue(
                    severity="block",
                    code="WR007",
                    message=(
                        f"Experimental implementation `{runtime_implementation_identifier}` cannot be wired "
                        f"as default runtime for `{responsibility.responsibility_id}`"
                    ),
                    file_path=project_root / ".bpfw/runtime_bindings.yaml",
                    recommendation="Switch runtime binding to stable active implementation",
                )
            )
        elif runtime_state == "disabled":
            issues.append(
                _make_issue(
                    severity="critical",
                    code="WR008",
                    message=(
                        f"Disabled implementation `{runtime_implementation_identifier}` is running for "
                        f"`{responsibility.responsibility_id}`"
                    ),
                    file_path=project_root / ".bpfw/runtime_bindings.yaml",
                    recommendation="Stop disabled implementation and bind to supported implementation",
                )
            )
        elif runtime_state == "deprecated":
            issues.append(
                _make_issue(
                    severity="block",
                    code="WR010",
                    message=(
                        f"Deprecated implementation `{runtime_implementation_identifier}` is running for "
                        f"`{responsibility.responsibility_id}`"
                    ),
                    file_path=project_root / ".bpfw/runtime_bindings.yaml",
                    recommendation="Migrate runtime binding away from deprecated implementation",
                )
            )
        if runtime_implementation_identifier != responsibility.active_implementation:
            issues.append(
                _make_issue(
                    severity="block",
                    code="WR005",
                    message=(
                        f"Runtime drift for `{responsibility.responsibility_id}`: "
                        f"blueprint declares `{responsibility.active_implementation}` but runtime uses "
                        f"`{runtime_implementation_identifier}`"
                    ),
                    file_path=project_root / ".bpfw/runtime_bindings.yaml",
                    recommendation="Align runtime binding with blueprint active_implementation",
                )
            )

    issues.sort(key=_issue_priority)
    return WiringVerificationResult(
        issues=issues,
        active_bindings=snapshot.active_bindings,
    )
