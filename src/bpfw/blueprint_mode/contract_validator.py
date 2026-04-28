"""Contract-level validation for Blueprint Mode callables."""

from __future__ import annotations

from pathlib import Path

from bpfw.blueprint.validator import validate_blueprint
from bpfw.blueprint_mode.models import BlueprintModeIssue, BlueprintModeValidationResult
from bpfw.blueprint_mode.policy import should_validate_blueprint_mode
from bpfw.blueprint_mode.validator import validate_blueprint_mode


def _issue(code: str, message: str, file_path: Path, recommendation: str) -> BlueprintModeIssue:
    return BlueprintModeIssue(
        severity="block",
        code=code,
        message=message,
        file_path=str(file_path),
        recommendation=recommendation,
    )


def validate_blueprint_mode_contracts(project_root: Path) -> BlueprintModeValidationResult:
    """Validate blueprint_mode contracts and callable alignment against allowed_symbols."""

    mode_result = validate_blueprint_mode(project_root=project_root)
    if mode_result.issues:
        return mode_result

    if not should_validate_blueprint_mode(mode_result.config):
        return mode_result

    blueprint_validation = validate_blueprint(project_root=project_root)
    if not blueprint_validation.is_valid or blueprint_validation.blueprint is None:
        first_error = blueprint_validation.errors[0]
        mode_result.issues.append(
            _issue(
                code="BM014",
                message=f"Blueprint must be valid before blueprint_mode contract checks: {first_error.message}",
                file_path=Path(first_error.file_path),
                recommendation=first_error.recommendation,
            )
        )
        return mode_result

    declared_symbols: set[str] = set()
    for responsibility in blueprint_validation.blueprint.responsibilities:
        for symbol in responsibility.allowed_symbols:
            declared_symbols.add(symbol)

    blueprint_path = project_root / "blueprint.yaml"
    for operation in mode_result.config.operations:
        if operation.callable not in declared_symbols:
            mode_result.issues.append(
                _issue(
                    code="BM015",
                    message=(
                        f"Operation `{operation.operation_id or '<missing-id>'}` callable "
                        f"`{operation.callable}` is not declared in any responsibility allowed_symbols"
                    ),
                    file_path=blueprint_path,
                    recommendation="Declare callable in responsibility.allowed_symbols or change operation callable",
                )
            )

    return mode_result
