"""Architecture profile validator and import rule orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bpfw.architecture.import_checker import check_import_rules
from bpfw.architecture.profile import (
    ArchitectureLoadError,
    ArchitectureProfile,
    LayerProfile,
    load_architecture_data,
)


@dataclass(slots=True)
class ArchitectureIssue:
    """Single architecture issue with severity and evidence."""

    severity: str
    code: str
    message: str
    file_path: str
    recommendation: str


@dataclass(slots=True)
class ArchitectureValidationResult:
    """Architecture validation result."""

    is_valid: bool
    profile: ArchitectureProfile | None = None
    errors: list[ArchitectureIssue] = field(default_factory=list)
    warnings: list[ArchitectureIssue] = field(default_factory=list)



def _is_repo_safe_path(value: str) -> bool:
    raw_path = Path(value)
    if raw_path.is_absolute():
        return False
    for part in raw_path.parts:
        if part == "..":
            return False
    return True



def _error(code: str, message: str, file_path: Path, recommendation: str) -> ArchitectureIssue:
    return ArchitectureIssue(
        severity="block",
        code=code,
        message=message,
        file_path=str(file_path),
        recommendation=recommendation,
    )



def _warning(code: str, message: str, file_path: Path, recommendation: str) -> ArchitectureIssue:
    return ArchitectureIssue(
        severity="warning",
        code=code,
        message=message,
        file_path=str(file_path),
        recommendation=recommendation,
    )



def validate_architecture(project_root: Path) -> ArchitectureValidationResult:
    """Load and validate architecture profile plus layer import constraints."""

    try:
        architecture_path, payload = load_architecture_data(project_root=project_root)
    except ArchitectureLoadError as error:
        return ArchitectureValidationResult(
            is_valid=False,
            errors=[
                ArchitectureIssue(
                    severity="block",
                    code="AR001",
                    message=str(error),
                    file_path=str(project_root / "architecture.yaml"),
                    recommendation="Create architecture.yaml with architecture_profile declaration",
                )
            ],
        )

    errors: list[ArchitectureIssue] = []
    warnings: list[ArchitectureIssue] = []

    architecture_profile_payload = payload.get("architecture_profile")
    if not isinstance(architecture_profile_payload, dict):
        return ArchitectureValidationResult(
            is_valid=False,
            errors=[
                _error(
                    code="AR002",
                    message="`architecture_profile` must be a mapping",
                    file_path=architecture_path,
                    recommendation="Define architecture_profile with id/layers/composition_roots",
                )
            ],
        )

    profile_id = str(architecture_profile_payload.get("id", "")).strip()
    layers_value = architecture_profile_payload.get("layers", [])
    composition_roots_value = architecture_profile_payload.get("composition_roots", [])

    if not isinstance(layers_value, list):
        errors.append(
            _error(
                code="AR003",
                message="`architecture_profile.layers` must be a list",
                file_path=architecture_path,
                recommendation="Set architecture_profile.layers as a YAML sequence",
            )
        )
        layers_value = []

    if not isinstance(composition_roots_value, list):
        errors.append(
            _warning(
                code="AR012",
                message="`composition_roots` should be a list",
                file_path=architecture_path,
                recommendation="Set composition_roots as a YAML sequence",
            )
        )
        composition_roots_value = []

    parsed_layers: list[LayerProfile] = []
    seen_layer_names: set[str] = set()

    for index, layer_value in enumerate(layers_value):
        if not isinstance(layer_value, dict):
            errors.append(
                _error(
                    code="AR004",
                    message=f"Layer index {index} must be a mapping",
                    file_path=architecture_path,
                    recommendation="Use key/value fields for each layer",
                )
            )
            continue

        for required_field in ("name", "path", "may_import"):
            if required_field not in layer_value:
                errors.append(
                    _error(
                        code="AR004",
                        message=f"Layer index {index} missing `{required_field}`",
                        file_path=architecture_path,
                        recommendation=f"Add `{required_field}` in layer index {index}",
                    )
                )

        layer_name = str(layer_value.get("name", "")).strip()
        layer_path = str(layer_value.get("path", "")).strip()
        may_import = layer_value.get("may_import", [])

        if not isinstance(may_import, list):
            errors.append(
                _error(
                    code="AR004",
                    message=f"Layer `{layer_name or index}` field `may_import` must be a list",
                    file_path=architecture_path,
                    recommendation="Set may_import as a YAML sequence",
                )
            )
            may_import = []

        if layer_name in seen_layer_names:
            errors.append(
                _error(
                    code="AR007",
                    message=f"Duplicate layer name `{layer_name}`",
                    file_path=architecture_path,
                    recommendation="Use unique layer names",
                )
            )
        seen_layer_names.add(layer_name)

        if layer_path and not _is_repo_safe_path(layer_path):
            errors.append(
                _error(
                    code="AR009",
                    message=f"Layer path `{layer_path}` is invalid",
                    file_path=architecture_path,
                    recommendation="Use repo-relative paths without absolute paths or '..'",
                )
            )

        parsed_layers.append(
            LayerProfile(
                name=layer_name,
                path=layer_path,
                may_import=[str(item).strip() for item in may_import],
            )
        )

    layer_name_set = {layer.name for layer in parsed_layers}
    for layer in parsed_layers:
        for imported_layer_name in layer.may_import:
            if imported_layer_name not in layer_name_set:
                errors.append(
                    _error(
                        code="AR010",
                        message=(
                            f"Layer `{layer.name}` declares unknown may_import target "
                            f"`{imported_layer_name}`"
                        ),
                        file_path=architecture_path,
                        recommendation="Reference only declared layer names in may_import",
                    )
                )

    architecture_profile = ArchitectureProfile(
        profile_id=profile_id,
        layers=parsed_layers,
        composition_roots=[str(item) for item in composition_roots_value],
        source_path=architecture_path,
    )

    if errors:
        return ArchitectureValidationResult(
            is_valid=False,
            profile=architecture_profile,
            errors=errors,
            warnings=warnings,
        )

    import_result = check_import_rules(project_root=project_root, profile=architecture_profile)
    for violation in import_result.violations:
        errors.append(
            ArchitectureIssue(
                severity="block",
                code=violation.code,
                message=violation.message,
                file_path=violation.file_path,
                recommendation=violation.recommendation,
            )
        )
    for warning in import_result.warnings:
        warnings.append(
            ArchitectureIssue(
                severity="warning",
                code=warning.code,
                message=warning.message,
                file_path=warning.file_path,
                recommendation=warning.recommendation,
            )
        )

    return ArchitectureValidationResult(
        is_valid=len(errors) == 0,
        profile=architecture_profile,
        errors=errors,
        warnings=warnings,
    )
