"""Minimum validator for executable Blueprint authority — MVP Catalog Mode."""

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


def _error(code: str, message: str, file_path: Path, recommendation: str) -> BlueprintValidationError:
    return BlueprintValidationError(
        code=code,
        message=message,
        file_path=str(file_path),
        recommendation=recommendation,
    )


def _is_repo_safe_path(path_value: str) -> bool:
    raw_path = Path(path_value)
    if raw_path.is_absolute():
        return False
    return all(part != ".." for part in raw_path.parts)


def validate_blueprint(project_root: Path) -> BlueprintValidationResult:
    """Load and validate minimum blueprint contract for MVP."""

    try:
        blueprint_path, payload, warnings = load_blueprint_data(project_root=project_root)
    except BlueprintLoadError as error:
        return BlueprintValidationResult(
            is_valid=False,
            errors=[
                BlueprintValidationError(
                    code="BP001",
                    message=str(error),
                    file_path=str(project_root / "bpfw/blueprint.yaml"),
                    recommendation="Create or repair bpfw/blueprint.yaml using the required schema",
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

    version_value = payload.get("version", 1)
    if not isinstance(version_value, int):
        errors.append(
            _error(
                code="BP020",
                message="`version` must be an integer",
                file_path=blueprint_path,
                recommendation="Set version to an integer value",
            )
        )
        version_value = 1

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
            errors.append(_error("BP005", f"Responsibility at index {index} must be a mapping", blueprint_path, "Use key/value fields"))
            continue

        for field_name in REQUIRED_RESPONSIBILITY_FIELDS:
            if field_name not in responsibility_value:
                errors.append(_error("BP006", f"Responsibility index {index} missing field `{field_name}`", blueprint_path, f"Add `{field_name}`"))

        responsibility_id = str(responsibility_value.get("responsibility_id", "")).strip()
        if responsibility_id:
            if responsibility_id in responsibility_ids:
                errors.append(_error("BP007", f"Duplicate responsibility_id `{responsibility_id}`", blueprint_path, "Use unique responsibility ids"))
            responsibility_ids.add(responsibility_id)

        allowed_files_value = responsibility_value.get("allowed_files", [])
        if not isinstance(allowed_files_value, list):
            errors.append(_error("BP008", f"`allowed_files` must be a list in responsibility `{responsibility_id or index}`", blueprint_path, "Set allowed_files as list"))
            allowed_files_value = []
        safe_allowed_files: list[str] = []
        for allowed_file in allowed_files_value:
            allowed_file_text = str(allowed_file)
            if not _is_repo_safe_path(allowed_file_text):
                errors.append(_error("BP009", f"Invalid path `{allowed_file_text}`", blueprint_path, "Use repo-relative safe paths"))
            else:
                safe_allowed_files.append(allowed_file_text)

        allowed_implementations_value = responsibility_value.get("allowed_implementations", [])
        if not isinstance(allowed_implementations_value, list):
            errors.append(_error("BP010", f"`allowed_implementations` must be a list in responsibility `{responsibility_id or index}`", blueprint_path, "Set allowed_implementations as list"))
            allowed_implementations_value = []

        parsed_implementations: list[BlueprintImplementation] = []
        for implementation_index, implementation_value in enumerate(allowed_implementations_value):
            if not isinstance(implementation_value, dict):
                errors.append(_error("BP011", f"Implementation index {implementation_index} in `{responsibility_id or index}` must be a mapping", blueprint_path, "Use key/value fields"))
                continue
            for field_name in REQUIRED_IMPLEMENTATION_FIELDS:
                if field_name not in implementation_value:
                    errors.append(_error("BP012", f"Implementation index {implementation_index} missing `{field_name}`", blueprint_path, f"Add `{field_name}`"))

            implementation_file = str(implementation_value.get("file", "")).strip()
            if implementation_file and not _is_repo_safe_path(implementation_file):
                errors.append(_error("BP013", f"Invalid implementation file path `{implementation_file}`", blueprint_path, "Use repo-relative safe paths"))

            parsed_implementations.append(
                BlueprintImplementation(
                    implementation_id=str(implementation_value.get("implementation_id", "")).strip(),
                    class_name=str(implementation_value.get("class_name", "")).strip(),
                    file=implementation_file,
                    lifecycle_state=str(implementation_value.get("lifecycle_state", "")).strip(),
                    replacement_id=implementation_value.get("replacement_id"),
                    disabled_reason=implementation_value.get("disabled_reason"),
                    removal_plan=implementation_value.get("removal_plan"),
                )
            )

        responsibility_model = BlueprintResponsibility(
            responsibility_id=responsibility_id,
            canonical_name=str(responsibility_value.get("canonical_name", "")).strip(),
            owner_layer=str(responsibility_value.get("owner_layer", "")).strip(),
            lifecycle_state=str(responsibility_value.get("lifecycle_state", "")).strip(),
            intent=(str(responsibility_value.get("intent", "")).strip() or None),
            allowed_files=safe_allowed_files,
            allowed_symbols=[str(item) for item in (responsibility_value.get("allowed_symbols") or [])],
            allowed_implementations=parsed_implementations,
            active_implementation=str(responsibility_value.get("active_implementation", "")).strip(),
            forbidden_duplicates=[str(item) for item in (responsibility_value.get("forbidden_duplicates") or [])],
            mutability=str(responsibility_value.get("mutability", "editable")).strip(),
            owner=str(responsibility_value.get("owner", "")).strip(),
        )

        implementation_index = build_implementation_index(responsibility_model)
        if responsibility_model.active_implementation and responsibility_model.active_implementation not in implementation_index:
            errors.append(_error("BP015", f"active_implementation `{responsibility_model.active_implementation}` does not exist", blueprint_path, "Use an existing implementation_id"))

        responsibilities.append(responsibility_model)

    locked_resources: list[LockedResource] = []
    for index, resource_value in enumerate(locked_resources_value):
        if not isinstance(resource_value, dict):
            errors.append(_error("BP016", f"locked_resource at index {index} must be a mapping", blueprint_path, "Use key/value fields"))
            continue
        missing_fields = [field_name for field_name in REQUIRED_LOCKED_RESOURCE_FIELDS if field_name not in resource_value]
        if missing_fields:
            errors.append(_error("BP017", f"locked_resource at index {index} missing fields: {', '.join(missing_fields)}", blueprint_path, "Complete locked_resource fields"))
            continue

        locked_resource_path = str(resource_value.get("path", "")).strip()
        if locked_resource_path and not _is_repo_safe_path(locked_resource_path):
            errors.append(_error("BP018", f"Invalid locked_resource path `{locked_resource_path}`", blueprint_path, "Use repo-relative safe paths"))

        locked_resources.append(
            LockedResource(
                resource_id=str(resource_value.get("resource_id", "")).strip(),
                path=locked_resource_path,
                mutability=str(resource_value.get("mutability", "")).strip(),
                owner=str(resource_value.get("owner", "")).strip(),
            )
        )

    if errors:
        return BlueprintValidationResult(is_valid=False, errors=errors, warnings=warnings)

    return BlueprintValidationResult(
        is_valid=True,
        blueprint=BlueprintModel(
            version=version_value,
            responsibilities=responsibilities,
            locked_resources=locked_resources,
            source_path=blueprint_path,
        ),
        warnings=warnings,
    )
