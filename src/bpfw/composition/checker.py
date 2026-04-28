"""Composition root checker orchestration."""

from __future__ import annotations

from pathlib import Path

from bpfw.blueprint.validator import validate_blueprint
from bpfw.composition.instantiation_scanner import scan_concrete_instantiations
from bpfw.composition.report import CompositionIssue, CompositionReport
from bpfw.composition.root import (
    CompositionRootError,
    is_authorized_composition_file,
    resolve_composition_roots,
)



def _error(code: str, message: str, file_path: Path, recommendation: str) -> CompositionIssue:
    return CompositionIssue(
        severity="block",
        code=code,
        message=message,
        file_path=str(file_path),
        recommendation=recommendation,
    )



def validate_composition(project_root: Path) -> CompositionReport:
    """Validate that concrete wiring occurs only in authorized composition roots."""

    blueprint_validation = validate_blueprint(project_root=project_root)
    if not blueprint_validation.is_valid or blueprint_validation.blueprint is None:
        blueprint_error = blueprint_validation.errors[0]
        return CompositionReport(
            is_valid=False,
            errors=[
                CompositionIssue(
                    severity="block",
                    code="CM001",
                    message=(
                        "Blueprint must be valid before composition checks: "
                        f"{blueprint_error.message}"
                    ),
                    file_path=blueprint_error.file_path,
                    recommendation=blueprint_error.recommendation,
                )
            ],
        )

    try:
        composition_roots = resolve_composition_roots(project_root=project_root)
    except CompositionRootError as error:
        return CompositionReport(
            is_valid=False,
            errors=[
                _error(
                    code="CM002",
                    message=str(error),
                    file_path=project_root / "architecture.yaml",
                    recommendation="Declare valid composition_roots in architecture.yaml",
                )
            ],
        )

    scan_result = scan_concrete_instantiations(
        project_root=project_root,
        blueprint=blueprint_validation.blueprint,
    )

    errors: list[CompositionIssue] = []
    for hit in scan_result.hits:
        if is_authorized_composition_file(hit.file_path, composition_roots):
            continue
        errors.append(
            _error(
                code="CM003",
                message=(
                    f"Concrete class `{hit.class_name}` is instantiated outside authorized "
                    f"composition roots"
                ),
                file_path=hit.file_path,
                recommendation=(
                    "Move concrete instantiation to declared composition roots "
                    "or src/bootstrap"
                ),
            )
        )

    return CompositionReport(is_valid=len(errors) == 0, errors=errors)
