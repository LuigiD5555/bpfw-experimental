"""Runtime binding collector using explicit metadata conventions."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from bpfw.blueprint.validator import validate_blueprint
from bpfw.composition.root import CompositionRootError, resolve_composition_roots
from bpfw.runtime.contract import (
    RuntimeBinding,
    RuntimeCollectionIssue,
    RuntimeCollectionResult,
    RuntimeSnapshotDocument,
)

_BINDING_MARKER_PREFIX = "# bpfw:binding "
_VALID_BINDING_KEYS = {
    "responsibility_id",
    "runtime_implementation",
    "implementation_id",
    "source",
}


def _warning(code: str, message: str, file_path: Path, recommendation: str) -> RuntimeCollectionIssue:
    return RuntimeCollectionIssue(
        severity="warning",
        code=code,
        message=message,
        file_path=str(file_path),
        recommendation=recommendation,
    )


def _error(code: str, message: str, file_path: Path, recommendation: str) -> RuntimeCollectionIssue:
    return RuntimeCollectionIssue(
        severity="block",
        code=code,
        message=message,
        file_path=str(file_path),
        recommendation=recommendation,
    )


def _to_display_path(path_value: Path, project_root: Path) -> str:
    try:
        return str(path_value.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path_value)


def _parse_marker_payload(raw_payload: str) -> dict[str, str]:
    parsed_entry: dict[str, str] = {}
    tokens = re.split(r"\s+", raw_payload.strip())
    for token in tokens:
        if "=" not in token:
            continue
        key, raw_value = token.split("=", 1)
        normalized_key = key.strip()
        if normalized_key not in _VALID_BINDING_KEYS:
            continue
        parsed_entry[normalized_key] = raw_value.strip().strip("'\"")
    return parsed_entry


def _load_runtime_bindings_from_wiring(project_root: Path) -> tuple[list[dict], list[RuntimeCollectionIssue]]:
    try:
        composition_roots = resolve_composition_roots(project_root=project_root)
    except CompositionRootError as error:
        return [], [
            _warning(
                code="RT006",
                message=f"Composition roots are not available for runtime marker detection: {error}",
                file_path=project_root / "architecture.yaml",
                recommendation="Fix architecture.yaml composition_roots or use .bpfw/runtime_bindings.yaml",
            )
        ]

    marker_entries: list[dict] = []
    warnings: list[RuntimeCollectionIssue] = []
    for root_file_path in sorted(composition_roots.root_files):
        if not root_file_path.exists():
            warnings.append(
                _warning(
                    code="RT007",
                    message=f"Composition root file does not exist: {_to_display_path(root_file_path, project_root)}",
                    file_path=root_file_path,
                    recommendation="Create composition root file or update architecture.yaml",
                )
            )
            continue

        try:
            wiring_lines = root_file_path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            warnings.append(
                _warning(
                    code="RT008",
                    message=f"Cannot read composition root file: {error}",
                    file_path=root_file_path,
                    recommendation="Ensure composition root files are readable",
                )
            )
            continue

        for line_number, line_content in enumerate(wiring_lines, start=1):
            stripped_line = line_content.strip()
            if not stripped_line.startswith(_BINDING_MARKER_PREFIX):
                continue

            raw_payload = stripped_line[len(_BINDING_MARKER_PREFIX) :]
            parsed_entry = _parse_marker_payload(raw_payload=raw_payload)
            responsibility_identifier = parsed_entry.get("responsibility_id", "")
            if not responsibility_identifier:
                warnings.append(
                    _warning(
                        code="RT009",
                        message=(
                            "Runtime marker without responsibility_id at "
                            f"{_to_display_path(root_file_path, project_root)}:{line_number}"
                        ),
                        file_path=root_file_path,
                        recommendation="Declare responsibility_id in bpfw:binding marker",
                    )
                )
                continue

            if not parsed_entry.get("source"):
                parsed_entry["source"] = f"{_to_display_path(root_file_path, project_root)}:{line_number}"
            marker_entries.append(parsed_entry)

    return marker_entries, warnings


def _load_runtime_bindings_data(runtime_bindings_path: Path) -> tuple[list[dict], list[RuntimeCollectionIssue]]:
    if not runtime_bindings_path.exists():
        return [], [
            _warning(
                code="RT001",
                message="runtime bindings file does not exist",
                file_path=runtime_bindings_path,
                recommendation="Create .bpfw/runtime_bindings.yaml with bindings entries",
            )
        ]

    try:
        payload = yaml.safe_load(runtime_bindings_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        return [], [
            _error(
                code="RT002",
                message=f"Invalid YAML in runtime bindings file: {error}",
                file_path=runtime_bindings_path,
                recommendation="Fix .bpfw/runtime_bindings.yaml syntax",
            )
        ]

    if payload is None:
        return [], []
    if not isinstance(payload, dict):
        return [], [
            _error(
                code="RT002",
                message="runtime bindings root must be a mapping",
                file_path=runtime_bindings_path,
                recommendation="Use mapping root with `bindings` or `active_bindings` list",
            )
        ]

    entries = payload.get("active_bindings")
    if entries is None:
        entries = payload.get("bindings", [])

    if not isinstance(entries, list):
        return [], [
            _error(
                code="RT002",
                message="`bindings`/`active_bindings` must be a list",
                file_path=runtime_bindings_path,
                recommendation="Set bindings as YAML sequence",
            )
        ]

    normalized_entries: list[dict] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        normalized_entries.append(item)

    return normalized_entries, []


def collect_runtime_snapshot(project_root: Path) -> RuntimeCollectionResult:
    """Collect runtime snapshot using blueprint expectations and runtime bindings metadata."""

    blueprint_validation = validate_blueprint(project_root=project_root)
    if not blueprint_validation.is_valid or blueprint_validation.blueprint is None:
        blueprint_error = blueprint_validation.errors[0]
        return RuntimeCollectionResult(
            errors=[
                _error(
                    code="RT003",
                    message=f"Blueprint must be valid before runtime snapshot: {blueprint_error.message}",
                    file_path=Path(blueprint_error.file_path),
                    recommendation=blueprint_error.recommendation,
                )
            ]
        )

    runtime_bindings_path = project_root / ".bpfw/runtime_bindings.yaml"
    binding_entries, binding_issues = _load_runtime_bindings_data(runtime_bindings_path)
    warnings = [issue for issue in binding_issues if issue.severity == "warning"]
    errors = [issue for issue in binding_issues if issue.severity == "block"]

    if errors:
        return RuntimeCollectionResult(errors=errors, warnings=warnings)

    if not binding_entries:
        marker_entries, marker_warnings = _load_runtime_bindings_from_wiring(project_root=project_root)
        if marker_entries:
            warnings = [warning for warning in warnings if warning.code != "RT001"]
            binding_entries = marker_entries
        warnings.extend(marker_warnings)

    entry_by_responsibility: dict[str, dict] = {}
    for entry in binding_entries:
        responsibility_id = str(entry.get("responsibility_id", "")).strip()
        if not responsibility_id:
            continue
        entry_by_responsibility[responsibility_id] = entry

    active_bindings: list[RuntimeBinding] = []
    for responsibility in blueprint_validation.blueprint.responsibilities:
        binding_entry = entry_by_responsibility.get(responsibility.responsibility_id, {})
        runtime_implementation = binding_entry.get("runtime_implementation")
        if runtime_implementation is None:
            runtime_implementation = binding_entry.get("implementation_id")

        runtime_implementation_text = None
        if runtime_implementation is not None:
            runtime_implementation_text = str(runtime_implementation).strip()

        source_text = str(binding_entry.get("source", ".bpfw/runtime_bindings.yaml")).strip()
        active_bindings.append(
            RuntimeBinding(
                responsibility_id=responsibility.responsibility_id,
                declared_active_implementation=responsibility.active_implementation,
                runtime_implementation=runtime_implementation_text,
                source=source_text,
            )
        )

        if runtime_implementation_text is None or runtime_implementation_text == "":
            warnings.append(
                _warning(
                    code="RT004",
                    message=(
                        "Runtime implementation is not declared for responsibility "
                        f"`{responsibility.responsibility_id}`"
                    ),
                    file_path=runtime_bindings_path,
                    recommendation="Add runtime_implementation in runtime bindings metadata",
                )
            )
        elif runtime_implementation_text != responsibility.active_implementation:
            warnings.append(
                _warning(
                    code="RT010",
                    message=(
                        f"Runtime implementation drift for `{responsibility.responsibility_id}`: "
                        f"blueprint declares `{responsibility.active_implementation}` "
                        f"but runtime reports `{runtime_implementation_text}`"
                    ),
                    file_path=runtime_bindings_path,
                    recommendation="Align runtime binding with blueprint active_implementation or update blueprint",
                )
            )

    for declared_responsibility_id in entry_by_responsibility:
        is_known = any(
            declared_responsibility_id == responsibility.responsibility_id
            for responsibility in blueprint_validation.blueprint.responsibilities
        )
        if not is_known:
            warnings.append(
                _warning(
                    code="RT005",
                    message=(
                        "Runtime binding references unknown responsibility_id "
                        f"`{declared_responsibility_id}`"
                    ),
                    file_path=runtime_bindings_path,
                    recommendation="Remove unknown binding or declare responsibility in blueprint",
                )
            )

    return RuntimeCollectionResult(
        snapshot=RuntimeSnapshotDocument(active_bindings=active_bindings),
        warnings=warnings,
        errors=errors,
    )
