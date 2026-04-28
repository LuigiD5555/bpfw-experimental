"""Lifecycle validator for responsibilities and implementations."""

from __future__ import annotations

from pathlib import Path

from bpfw.blueprint.models import BlueprintModel, BlueprintResponsibility, BlueprintValidationError
from bpfw.lifecycle.states import OFFICIAL_STATES
from bpfw.lifecycle.transition_policy import can_be_active_by_default



def _error(code: str, message: str, blueprint_path: Path, recommendation: str) -> BlueprintValidationError:
    return BlueprintValidationError(
        code=code,
        message=message,
        file_path=str(blueprint_path),
        recommendation=recommendation,
    )



def _validate_responsibility_state(
    responsibility: BlueprintResponsibility,
    blueprint_path: Path,
) -> list[BlueprintValidationError]:
    errors: list[BlueprintValidationError] = []
    if responsibility.lifecycle_state not in OFFICIAL_STATES:
        errors.append(
            _error(
                code="LC010",
                message=(
                    f"Unknown responsibility lifecycle_state `{responsibility.lifecycle_state}` in "
                    f"`{responsibility.responsibility_id}`"
                ),
                blueprint_path=blueprint_path,
                recommendation="Use one of: planned, active, experimental, disabled, deprecated, legacy",
            )
        )
    return errors



def _validate_implementations(
    responsibility: BlueprintResponsibility,
    blueprint_path: Path,
    explicit_experimental_approval: bool,
) -> list[BlueprintValidationError]:
    errors: list[BlueprintValidationError] = []
    implementation_by_id = {
        implementation.implementation_id: implementation
        for implementation in responsibility.allowed_implementations
    }

    for implementation in responsibility.allowed_implementations:
        if implementation.lifecycle_state not in OFFICIAL_STATES:
            errors.append(
                _error(
                    code="LC010",
                    message=(
                        f"Unknown implementation lifecycle_state `{implementation.lifecycle_state}` in "
                        f"`{responsibility.responsibility_id}/{implementation.implementation_id}`"
                    ),
                    blueprint_path=blueprint_path,
                    recommendation="Use one of: planned, active, experimental, disabled, deprecated, legacy",
                )
            )

        if implementation.lifecycle_state == "disabled" and not implementation.disabled_reason:
            errors.append(
                _error(
                    code="LC007",
                    message=(
                        f"disabled implementation `{implementation.implementation_id}` in "
                        f"`{responsibility.responsibility_id}` requires disabled_reason"
                    ),
                    blueprint_path=blueprint_path,
                    recommendation="Set disabled_reason with a concrete reason",
                )
            )

        if implementation.lifecycle_state == "deprecated":
            if not implementation.replacement_id and not implementation.removal_plan:
                errors.append(
                    _error(
                        code="LC008",
                        message=(
                            f"deprecated implementation `{implementation.implementation_id}` in "
                            f"`{responsibility.responsibility_id}` requires replacement_id or removal_plan"
                        ),
                        blueprint_path=blueprint_path,
                        recommendation="Set replacement_id or removal_plan",
                    )
                )

    selected_implementation = implementation_by_id.get(responsibility.active_implementation)
    if selected_implementation is not None:
        decision = can_be_active_by_default(
            state=selected_implementation.lifecycle_state,
            explicit_approval=explicit_experimental_approval,
        )
        if not decision.allowed and decision.code and decision.message and decision.recommendation:
            errors.append(
                _error(
                    code=decision.code,
                    message=(
                        f"{decision.message} in responsibility `{responsibility.responsibility_id}` "
                        f"for `{selected_implementation.implementation_id}`"
                    ),
                    blueprint_path=blueprint_path,
                    recommendation=decision.recommendation,
                )
            )

    return errors



def validate_lifecycle(
    blueprint: BlueprintModel,
    explicit_experimental_approval: bool = False,
) -> list[BlueprintValidationError]:
    """Validate lifecycle constraints for Prompt 2."""

    if blueprint.source_path is None:
        blueprint_path = Path("blueprint.yaml")
    else:
        blueprint_path = blueprint.source_path

    errors: list[BlueprintValidationError] = []
    for responsibility in blueprint.responsibilities:
        errors.extend(_validate_responsibility_state(responsibility, blueprint_path))
        errors.extend(
            _validate_implementations(
                responsibility=responsibility,
                blueprint_path=blueprint_path,
                explicit_experimental_approval=explicit_experimental_approval,
            )
        )

    return errors
