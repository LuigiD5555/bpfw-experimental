"""Minimum validator for executable Blueprint authority."""

from __future__ import annotations

from pathlib import Path

from bpfw.blueprint.loader import BlueprintLoadError, load_blueprint_data
from bpfw.blueprint.models import (
    BlueprintImplementation,
    BlueprintModel,
    BlueprintResponsibility,
    BlueprintValidationError,
    BlueprintValidationResult,
    LockedResource,
)
from bpfw.blueprint.resolver import build_implementation_index
from bpfw.blueprint.schema import (
    REQUIRED_IMPLEMENTATION_FIELDS,
    REQUIRED_LOCKED_RESOURCE_FIELDS,
    REQUIRED_RESPONSIBILITY_FIELDS,
    REQUIRED_ROOT_FIELDS,
)
from bpfw.lifecycle.lifecycle_reporter import summarize_lifecycle_errors
from bpfw.lifecycle.validator import validate_lifecycle



def _error(code: str, message: str, file_path: Path, recommendation: str) -> BlueprintValidationError:
    return BlueprintValidationError(
        code=code,
        message=message,
        file_path=str(file_path),
        recommendation=recommendation,
    )



def _is_repo_safe_path(value: str) -> bool:
    raw_path = Path(value)
    if raw_path.is_absolute():
        return False
    for part in raw_path.parts:
        if part == "..":
            return False
    return True



def validate_blueprint(project_root: Path) -> BlueprintValidationResult:
    """Load and validate minimum phase-1 blueprint contract."""

    try:
        blueprint_path, payload = load_blueprint_data(project_root=project_root)
    except BlueprintLoadError as error:
        return BlueprintValidationResult(
            is_valid=False,
            errors=[
                BlueprintValidationError(
                    code="BP001",
                    message=str(error),
                    file_path=str(project_root / "blueprint.yaml"),
                    recommendation="Create/repair blueprint.yaml using the required schema",
                )
            ],
        )

    errors: list[BlueprintValidationError] = []

    for field_name in REQUIRED_ROOT_FIELDS:
        if field_name not in payload:
            errors.append(
                _error(
                    code="BP002",
                    message=f"Missing root field: {field_name}",
                    file_path=blueprint_path,
                    recommendation=f"Add `{field_name}` to blueprint root",
                )
            )

    version_value = payload.get("version")
    responsibilities_value = payload.get("responsibilities")

    if not isinstance(responsibilities_value, list):
        errors.append(
            _error(
                code="BP003",
                message="`responsibilities` must be a list",
                file_path=blueprint_path,
                recommendation="Set responsibilities as a YAML sequence",
            )
        )
        responsibilities_value = []
    if version_value is None:
        pass
    elif not isinstance(version_value, int):
        errors.append(
            _error(
                code="BP020",
                message="`version` must be an integer",
                file_path=blueprint_path,
                recommendation="Set version to an integer value (example: 1)",
            )
        )

    locked_resources_value = payload.get("locked_resources", [])
    if not isinstance(locked_resources_value, list):
        errors.append(
            _error(
                code="BP004",
                message="`locked_resources` must be a list when present",
                file_path=blueprint_path,
                recommendation="Set locked_resources as a YAML sequence",
            )
        )
        locked_resources_value = []

    responsibility_ids: set[str] = set()
    responsibilities: list[BlueprintResponsibility] = []

    for index, responsibility_value in enumerate(responsibilities_value):
        if not isinstance(responsibility_value, dict):
            errors.append(
                _error(
                    code="BP005",
                    message=f"Responsibility at index {index} must be a mapping",
                    file_path=blueprint_path,
                    recommendation="Use key/value fields for each responsibility",
                )
            )
            continue

        for field_name in REQUIRED_RESPONSIBILITY_FIELDS:
            if field_name not in responsibility_value:
                errors.append(
                    _error(
                        code="BP006",
                        message=f"Responsibility index {index} missing field `{field_name}`",
                        file_path=blueprint_path,
                        recommendation=f"Add `{field_name}` in responsibility index {index}",
                    )
                )

        responsibility_id = str(responsibility_value.get("responsibility_id", "")).strip()
        if responsibility_id:
            if responsibility_id in responsibility_ids:
                errors.append(
                    _error(
                        code="BP007",
                        message=f"Duplicate responsibility_id `{responsibility_id}`",
                        file_path=blueprint_path,
                        recommendation="Ensure each responsibility_id is unique",
                    )
                )
            responsibility_ids.add(responsibility_id)

        allowed_files_value = responsibility_value.get("allowed_files", [])
        if not isinstance(allowed_files_value, list):
            errors.append(
                _error(
                    code="BP008",
                    message=f"`allowed_files` must be a list in responsibility `{responsibility_id or index}`",
                    file_path=blueprint_path,
                    recommendation="Set allowed_files as a YAML sequence",
                )
            )
            allowed_files_value = []

        safe_allowed_files: list[str] = []
        for allowed_file in allowed_files_value:
            allowed_file_text = str(allowed_file)
            if not _is_repo_safe_path(allowed_file_text):
                errors.append(
                    _error(
                        code="BP009",
                        message=(
                            f"Path `{allowed_file_text}` is invalid in responsibility "
                            f"`{responsibility_id or index}`"
                        ),
                        file_path=blueprint_path,
                        recommendation="Use only repo-relative paths without absolute paths or '..'",
                    )
                )
            else:
                safe_allowed_files.append(allowed_file_text)

        allowed_implementations_value = responsibility_value.get("allowed_implementations", [])
        if not isinstance(allowed_implementations_value, list):
            errors.append(
                _error(
                    code="BP010",
                    message=(
                        "`allowed_implementations` must be a list in responsibility "
                        f"`{responsibility_id or index}`"
                    ),
                    file_path=blueprint_path,
                    recommendation="Set allowed_implementations as a YAML sequence",
                )
            )
            allowed_implementations_value = []

        parsed_implementations: list[BlueprintImplementation] = []
        active_implementations_in_lifecycle = 0

        for implementation_index, implementation_value in enumerate(allowed_implementations_value):
            if not isinstance(implementation_value, dict):
                errors.append(
                    _error(
                        code="BP011",
                        message=(
                            f"Implementation index {implementation_index} in responsibility "
                            f"`{responsibility_id or index}` must be a mapping"
                        ),
                        file_path=blueprint_path,
                        recommendation="Use key/value fields for each implementation",
                    )
                )
                continue

            for field_name in REQUIRED_IMPLEMENTATION_FIELDS:
                if field_name not in implementation_value:
                    errors.append(
                        _error(
                            code="BP012",
                            message=(
                                f"Implementation index {implementation_index} in responsibility "
                                f"`{responsibility_id or index}` missing `{field_name}`"
                            ),
                            file_path=blueprint_path,
                            recommendation=f"Add `{field_name}` in implementation index {implementation_index}",
                        )
                    )

            implementation_file = str(implementation_value.get("file", "")).strip()
            if implementation_file and not _is_repo_safe_path(implementation_file):
                errors.append(
                    _error(
                        code="BP013",
                        message=(
                            f"Implementation file path `{implementation_file}` is invalid in "
                            f"responsibility `{responsibility_id or index}`"
                        ),
                        file_path=blueprint_path,
                        recommendation="Use only repo-relative paths without absolute paths or '..'",
                    )
                )

            lifecycle_state_value = str(implementation_value.get("lifecycle_state", "")).strip()
            if lifecycle_state_value == "active":
                active_implementations_in_lifecycle += 1

            parsed_implementations.append(
                BlueprintImplementation(
                    implementation_id=str(implementation_value.get("implementation_id", "")).strip(),
                    class_name=str(implementation_value.get("class_name", "")).strip(),
                    file=implementation_file,
                    lifecycle_state=lifecycle_state_value,
                    replacement_id=(
                        str(implementation_value.get("replacement_id")).strip()
                        if implementation_value.get("replacement_id") is not None
                        else None
                    ),
                    disabled_reason=(
                        str(implementation_value.get("disabled_reason")).strip()
                        if implementation_value.get("disabled_reason") is not None
                        else None
                    ),
                    removal_plan=(
                        str(implementation_value.get("removal_plan")).strip()
                        if implementation_value.get("removal_plan") is not None
                        else None
                    ),
                )
            )

        if active_implementations_in_lifecycle > 1:
            errors.append(
                _error(
                    code="BP014",
                    message=(
                        "More than one implementation has lifecycle_state=active in "
                        f"responsibility `{responsibility_id or index}`"
                    ),
                    file_path=blueprint_path,
                    recommendation="Keep only one implementation with lifecycle_state: active",
                )
            )

        responsibility_model = BlueprintResponsibility(
            responsibility_id=responsibility_id,
            canonical_name=str(responsibility_value.get("canonical_name", "")).strip(),
            owner_layer=str(responsibility_value.get("owner_layer", "")).strip(),
            lifecycle_state=str(responsibility_value.get("lifecycle_state", "")).strip(),
            allowed_files=safe_allowed_files,
            allowed_symbols=[str(item) for item in responsibility_value.get("allowed_symbols", [])],
            allowed_implementations=parsed_implementations,
            active_implementation=str(responsibility_value.get("active_implementation", "")).strip(),
            forbidden_duplicates=[str(item) for item in responsibility_value.get("forbidden_duplicates", [])],
            mutability=str(responsibility_value.get("mutability", "editable")).strip(),
            owner=str(responsibility_value.get("owner", "")).strip(),
        )

        implementation_index = build_implementation_index(responsibility_model)
        if responsibility_model.active_implementation not in implementation_index:
            errors.append(
                _error(
                    code="BP015",
                    message=(
                        f"active_implementation `{responsibility_model.active_implementation}` does not exist "
                        f"in responsibility `{responsibility_id or index}`"
                    ),
                    file_path=blueprint_path,
                    recommendation="Set active_implementation to an existing implementation_id",
                )
            )

        responsibilities.append(responsibility_model)

    locked_resources: list[LockedResource] = []
    for index, resource_value in enumerate(locked_resources_value):
        if not isinstance(resource_value, dict):
            errors.append(
                _error(
                    code="BP016",
                    message=f"locked_resource at index {index} must be a mapping",
                    file_path=blueprint_path,
                    recommendation="Use key/value fields for locked_resource entries",
                )
            )
            continue

        for field_name in REQUIRED_LOCKED_RESOURCE_FIELDS:
            if field_name not in resource_value:
                errors.append(
                    _error(
                        code="BP017",
                        message=f"locked_resource index {index} missing `{field_name}`",
                        file_path=blueprint_path,
                        recommendation=f"Add `{field_name}` in locked_resource index {index}",
                    )
                )

        resource_path = str(resource_value.get("path", "")).strip()
        if resource_path and not _is_repo_safe_path(resource_path):
            errors.append(
                _error(
                    code="BP018",
                    message=f"locked_resource path `{resource_path}` is invalid",
                    file_path=blueprint_path,
                    recommendation="Use only repo-relative paths without absolute paths or '..'",
                )
            )

        owner_value = str(resource_value.get("owner", "")).strip()
        if not owner_value:
            errors.append(
                _error(
                    code="BP019",
                    message=f"locked_resource index {index} must define owner",
                    file_path=blueprint_path,
                    recommendation="Add a non-empty owner field",
                )
            )

        locked_resources.append(
            LockedResource(
                resource_id=str(resource_value.get("resource_id", "")).strip(),
                path=resource_path,
                mutability=str(resource_value.get("mutability", "")).strip(),
                owner=owner_value,
            )
        )

    if errors:
        return BlueprintValidationResult(is_valid=False, errors=errors)

    version_integer = int(version_value)
    blueprint_model = BlueprintModel(
        version=version_integer,
        responsibilities=responsibilities,
        locked_resources=locked_resources,
        source_path=blueprint_path,
    )
    lifecycle_errors = validate_lifecycle(blueprint=blueprint_model, explicit_experimental_approval=False)
    if lifecycle_errors:
        lifecycle_summary = summarize_lifecycle_errors(lifecycle_errors)
        first_error = lifecycle_errors[0]
        return BlueprintValidationResult(
            is_valid=False,
            errors=[
                BlueprintValidationError(
                    code=first_error.code,
                    message=first_error.message,
                    file_path=first_error.file_path,
                    recommendation=(
                        f"{first_error.recommendation} "
                        f"(lifecycle_error_count={lifecycle_summary['lifecycle_error_count']})"
                    ),
                )
            ],
        )
    return BlueprintValidationResult(is_valid=True, blueprint=blueprint_model)
