"""Blueprint Mode schema validator (opt-in)."""

from __future__ import annotations

from pathlib import Path

from bpfw.blueprint.loader import BlueprintLoadError, load_blueprint_data
from bpfw.blueprint_mode.models import (
    BlueprintModeConfig,
    BlueprintModeIssue,
    BlueprintModeOperation,
    BlueprintModeSideEffects,
    BlueprintModeValidationResult,
)
from bpfw.blueprint_mode.policy import should_validate_blueprint_mode
from bpfw.blueprint_mode.schema import (
    BLUEPRINT_MODE_ENABLED_KEY,
    BLUEPRINT_MODE_KEY,
    BLUEPRINT_MODE_OPERATIONS_KEY,
    OPERATION_ALLOWED_ERRORS_KEY,
    OPERATION_CALLABLE_KEY,
    OPERATION_ID_KEY,
    OPERATION_INPUT_CONTRACT_KEY,
    OPERATION_OUTPUT_CONTRACT_KEY,
    OPERATION_SIDE_EFFECTS_KEY,
    SIDE_EFFECTS_ALLOWED_KEY,
    SIDE_EFFECTS_FORBIDDEN_KEY,
)


def _issue(code: str, message: str, file_path: Path, recommendation: str) -> BlueprintModeIssue:
    return BlueprintModeIssue(
        severity="block",
        code=code,
        message=message,
        file_path=str(file_path),
        recommendation=recommendation,
    )


def validate_blueprint_mode(project_root: Path) -> BlueprintModeValidationResult:
    """Validate blueprint_mode declaration without executing runtime callables."""

    blueprint_path = project_root / "blueprint.yaml"
    try:
        _, payload = load_blueprint_data(project_root=project_root)
    except BlueprintLoadError as error:
        return BlueprintModeValidationResult(
            issues=[
                _issue(
                    code="BM001",
                    message=f"Blueprint load failed for blueprint_mode validation: {error}",
                    file_path=blueprint_path,
                    recommendation="Fix blueprint.yaml before validating blueprint_mode",
                )
            ]
        )

    blueprint_mode_raw = payload.get(BLUEPRINT_MODE_KEY)
    if blueprint_mode_raw is None:
        return BlueprintModeValidationResult(config=BlueprintModeConfig(enabled=False, operations=[]))

    if not isinstance(blueprint_mode_raw, dict):
        return BlueprintModeValidationResult(
            issues=[
                _issue(
                    code="BM002",
                    message="`blueprint_mode` must be a mapping when present",
                    file_path=blueprint_path,
                    recommendation="Define blueprint_mode as YAML mapping with enabled/operations fields",
                )
            ]
        )

    enabled_raw = blueprint_mode_raw.get(BLUEPRINT_MODE_ENABLED_KEY, False)
    if not isinstance(enabled_raw, bool):
        return BlueprintModeValidationResult(
            issues=[
                _issue(
                    code="BM003",
                    message="`blueprint_mode.enabled` must be boolean",
                    file_path=blueprint_path,
                    recommendation="Set blueprint_mode.enabled to true or false",
                )
            ]
        )

    config = BlueprintModeConfig(enabled=enabled_raw, operations=[])
    if not should_validate_blueprint_mode(config):
        return BlueprintModeValidationResult(config=config)

    operations_raw = blueprint_mode_raw.get(BLUEPRINT_MODE_OPERATIONS_KEY)
    if not isinstance(operations_raw, list) or not operations_raw:
        return BlueprintModeValidationResult(
            config=config,
            issues=[
                _issue(
                    code="BM004",
                    message="`blueprint_mode.operations` must exist as non-empty list when enabled=true",
                    file_path=blueprint_path,
                    recommendation="Declare at least one operation contract under blueprint_mode.operations",
                )
            ],
        )

    issues: list[BlueprintModeIssue] = []
    operations: list[BlueprintModeOperation] = []

    for index, operation_raw in enumerate(operations_raw):
        if not isinstance(operation_raw, dict):
            issues.append(
                _issue(
                    code="BM005",
                    message=f"Operation at index {index} must be a mapping",
                    file_path=blueprint_path,
                    recommendation="Use key/value fields for each blueprint_mode operation",
                )
            )
            continue

        operation_id = str(operation_raw.get(OPERATION_ID_KEY, "")).strip()
        callable_symbol = str(operation_raw.get(OPERATION_CALLABLE_KEY, "")).strip()
        output_contract_raw = operation_raw.get(OPERATION_OUTPUT_CONTRACT_KEY)

        if not operation_id:
            issues.append(
                _issue(
                    code="BM006",
                    message=f"Operation index {index} missing `operation_id`",
                    file_path=blueprint_path,
                    recommendation="Define operation_id for every blueprint_mode operation",
                )
            )

        if not callable_symbol:
            issues.append(
                _issue(
                    code="BM007",
                    message=f"Operation `{operation_id or index}` missing `callable`",
                    file_path=blueprint_path,
                    recommendation="Define callable symbol for every blueprint_mode operation",
                )
            )

        if output_contract_raw is None or not isinstance(output_contract_raw, dict) or not output_contract_raw:
            issues.append(
                _issue(
                    code="BM008",
                    message=f"Operation `{operation_id or index}` missing valid `output_contract`",
                    file_path=blueprint_path,
                    recommendation="Define non-empty output_contract mapping for every operation",
                )
            )

        input_contract_raw = operation_raw.get(OPERATION_INPUT_CONTRACT_KEY, {})
        if not isinstance(input_contract_raw, dict):
            issues.append(
                _issue(
                    code="BM009",
                    message=f"Operation `{operation_id or index}` field `input_contract` must be mapping",
                    file_path=blueprint_path,
                    recommendation="Set input_contract as YAML mapping",
                )
            )
            input_contract_raw = {}

        allowed_errors_raw = operation_raw.get(OPERATION_ALLOWED_ERRORS_KEY, [])
        if not isinstance(allowed_errors_raw, list):
            issues.append(
                _issue(
                    code="BM010",
                    message=f"Operation `{operation_id or index}` field `allowed_errors` must be list",
                    file_path=blueprint_path,
                    recommendation="Set allowed_errors as YAML sequence",
                )
            )
            allowed_errors_raw = []

        side_effects_raw = operation_raw.get(OPERATION_SIDE_EFFECTS_KEY, {})
        if side_effects_raw is None:
            side_effects_raw = {}
        if not isinstance(side_effects_raw, dict):
            issues.append(
                _issue(
                    code="BM011",
                    message=f"Operation `{operation_id or index}` field `side_effects` must be mapping",
                    file_path=blueprint_path,
                    recommendation="Define side_effects as mapping with allowed/forbidden lists",
                )
            )
            side_effects_raw = {}

        forbidden_effects = side_effects_raw.get(SIDE_EFFECTS_FORBIDDEN_KEY, [])
        if forbidden_effects is None:
            forbidden_effects = []
        if not isinstance(forbidden_effects, list):
            issues.append(
                _issue(
                    code="BM012",
                    message=(
                        f"Operation `{operation_id or index}` field "
                        "`side_effects.forbidden` must be list"
                    ),
                    file_path=blueprint_path,
                    recommendation="Set side_effects.forbidden as YAML sequence",
                )
            )
            forbidden_effects = []

        allowed_effects = side_effects_raw.get(SIDE_EFFECTS_ALLOWED_KEY, [])
        if allowed_effects is None:
            allowed_effects = []
        if not isinstance(allowed_effects, list):
            issues.append(
                _issue(
                    code="BM013",
                    message=(
                        f"Operation `{operation_id or index}` field "
                        "`side_effects.allowed` must be list"
                    ),
                    file_path=blueprint_path,
                    recommendation="Set side_effects.allowed as YAML sequence",
                )
            )
            allowed_effects = []

        operations.append(
            BlueprintModeOperation(
                operation_id=operation_id,
                callable=callable_symbol,
                input_contract={str(key): str(value) for key, value in input_contract_raw.items()},
                output_contract=(
                    {str(key): str(value) for key, value in output_contract_raw.items()}
                    if isinstance(output_contract_raw, dict)
                    else {}
                ),
                allowed_errors=[str(item) for item in allowed_errors_raw],
                side_effects=BlueprintModeSideEffects(
                    allowed=[str(item) for item in allowed_effects],
                    forbidden=[str(item) for item in forbidden_effects],
                ),
            )
        )

    config.operations = operations
    return BlueprintModeValidationResult(config=config, issues=issues)
