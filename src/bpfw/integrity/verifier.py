"""Integrity verification against signed manifest — MVP Catalog Mode."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bpfw.blueprint.loader import BlueprintLoadError, load_blueprint_data
from bpfw.integrity.hash_provider import compute_sha256, read_file_size
from bpfw.integrity.manifest import (
    IntegrityManifestError,
    load_manifest,
    manifest_path,
    resolve_protected_targets,
)
from bpfw.integrity.signer import IntegritySigningError, verify_payload_signature


_PRECONDITION_ISSUE_CODES = {"INT001", "INT002"}


@dataclass(slots=True, frozen=True)
class IntegrityIssue:
    """Single integrity verification issue."""

    code: str
    message: str
    severity: str
    recommendation: str
    file_path: str = ""


@dataclass(slots=True)
class IntegrityVerificationResult:
    """Verification result for project manifest and protected files."""

    is_valid: bool
    manifest_path: str
    checked_files: int
    issues: list[IntegrityIssue] = field(default_factory=list)

    @property
    def only_precondition_issues(self) -> bool:
        if not self.issues:
            return False
        return all(issue.code in _PRECONDITION_ISSUE_CODES for issue in self.issues)


def _issue(code: str, message: str, severity: str, recommendation: str, file_path: str = "") -> IntegrityIssue:
    return IntegrityIssue(
        code=code,
        message=message,
        severity=severity,
        recommendation=recommendation,
        file_path=file_path,
    )


def _validate_manifest_shape(manifest_payload: dict[str, Any], manifest_file_path: Path) -> list[IntegrityIssue]:
    """Validate manifest has required fields with correct types."""
    issues: list[IntegrityIssue] = []

    version_value = manifest_payload.get("version")
    if not isinstance(version_value, int):
        issues.append(
            _issue(
                code="INT003",
                message="Integrity manifest `version` must be an integer",
                severity="block",
                recommendation="Regenerate manifest with `bpfw init`",
                file_path=str(manifest_file_path),
            )
        )

    updated_at_value = manifest_payload.get("updated_at")
    if not isinstance(updated_at_value, str) or not updated_at_value.strip():
        issues.append(
            _issue(
                code="INT003",
                message="Integrity manifest `updated_at` must be a non-empty string",
                severity="block",
                recommendation="Regenerate manifest with `bpfw init`",
                file_path=str(manifest_file_path),
            )
        )

    files_value = manifest_payload.get("files")
    if not isinstance(files_value, list):
        issues.append(
            _issue(
                code="INT003",
                message="Integrity manifest `files` must be a list",
                severity="block",
                recommendation="Regenerate manifest with `bpfw init`",
                file_path=str(manifest_file_path),
            )
        )

    signature_value = manifest_payload.get("signature")
    if not isinstance(signature_value, str) or not signature_value.strip():
        issues.append(
            _issue(
                code="INT003",
                message="Integrity manifest `signature` must be a non-empty string",
                severity="block",
                recommendation="Regenerate manifest with `bpfw init`",
                file_path=str(manifest_file_path),
            )
        )

    return issues


def _verify_manifest_signature(manifest_payload: dict[str, Any], manifest_file_path: Path) -> list[IntegrityIssue]:
    """Verify manifest signature is valid."""
    signature_value = str(manifest_payload.get("signature", "")).strip()
    if not signature_value:
        return [
            _issue(
                code="INT003",
                message="Integrity manifest signature is missing",
                severity="block",
                recommendation="Regenerate manifest with `bpfw init`",
                file_path=str(manifest_file_path),
            )
        ]

    signable_payload = {key: value for key, value in manifest_payload.items() if key != "signature"}
    try:
        is_valid_signature = verify_payload_signature(
            payload=signable_payload, signature=signature_value, project_root=manifest_file_path.parent.parent
        )
    except IntegritySigningError as error:
        return [
            _issue(
                code="INT001",
                message=str(error),
                severity="block",
                recommendation="Set BPFW_MANIFEST_HMAC_KEY before running integrity checks",
                file_path=str(manifest_file_path),
            )
        ]

    if not is_valid_signature:
        return [
            _issue(
                code="INT004",
                message="Integrity manifest signature is invalid",
                severity="critical",
                recommendation="Run `bpfw init` from trusted state to regenerate signature",
                file_path=str(manifest_file_path),
            )
        ]

    return []


def _validate_manifest_coverage(project_root: Path, manifest_payload: dict[str, Any]) -> list[IntegrityIssue]:
    """Verify manifest covers all protected targets."""
    expected_targets = resolve_protected_targets(project_root=project_root, require_valid_blueprint=False)
    expected_paths = {target.path for target in expected_targets}

    files_value = manifest_payload.get("files")
    if not isinstance(files_value, list):
        return []

    manifest_paths: set[str] = set()
    for file_entry in files_value:
        if not isinstance(file_entry, dict):
            continue
        file_path_value = file_entry.get("path")
        if isinstance(file_path_value, str) and file_path_value.strip():
            manifest_paths.add(file_path_value)

    missing_paths = sorted(expected_paths - manifest_paths)
    if not missing_paths:
        return []

    first_missing_path = missing_paths[0]
    return [
        _issue(
            code="INT005",
            message=f"Integrity manifest is missing protected file `{first_missing_path}`",
            severity="block",
            recommendation="Regenerate manifest with `bpfw init`",
            file_path=str(project_root / first_missing_path),
        )
    ]


def _locked_resource_ids(project_root: Path) -> set[str]:
    """Get set of locked resource IDs from blueprint."""
    locked_resource_ids = {"project_blueprint"}
    try:
        _, blueprint_payload, _warnings = load_blueprint_data(project_root=project_root)
    except BlueprintLoadError:
        return locked_resource_ids

    locked_resources = blueprint_payload.get("locked_resources")
    if not isinstance(locked_resources, list):
        return locked_resource_ids

    for resource in locked_resources:
        if not isinstance(resource, dict):
            continue
        if str(resource.get("mutability", "")).strip() != "locked":
            continue
        resource_id = str(resource.get("resource_id", "")).strip()
        if resource_id:
            locked_resource_ids.add(resource_id)

    return locked_resource_ids


def _verify_file_entries(
    *,
    project_root: Path,
    manifest_payload: dict[str, Any],
    locked_resource_ids: set[str],
) -> tuple[int, list[IntegrityIssue]]:
    """Verify all file entries in manifest match current files."""
    files_value = manifest_payload.get("files")
    if not isinstance(files_value, list):
        return 0, []

    checked_files = 0
    issues: list[IntegrityIssue] = []

    for file_entry in files_value:
        if not isinstance(file_entry, dict):
            issues.append(
                _issue(
                    code="INT003",
                    message="Integrity manifest contains invalid file entry",
                    severity="block",
                    recommendation="Regenerate manifest with `bpfw init`",
                    file_path=str(manifest_path(project_root=project_root)),
                )
            )
            continue

        file_path_value = str(file_entry.get("path", "")).strip()
        resource_id_value = str(file_entry.get("resource_id", "")).strip()
        expected_hash = str(file_entry.get("sha256", "")).strip()
        size_value = file_entry.get("size")

        if not file_path_value or not resource_id_value or not expected_hash or not isinstance(size_value, int):
            issues.append(
                _issue(
                    code="INT003",
                    message="Integrity manifest file entry is incomplete",
                    severity="block",
                    recommendation="Regenerate manifest with `bpfw init`",
                    file_path=str(manifest_path(project_root=project_root)),
                )
            )
            continue

        absolute_path = project_root / file_path_value
        checked_files += 1

        if not absolute_path.exists():
            issues.append(
                _issue(
                    code="INT006",
                    message=f"Protected file is missing: {file_path_value}",
                    severity="block",
                    recommendation="Restore the missing file or regenerate manifest from trusted state",
                    file_path=str(absolute_path),
                )
            )
            continue

        if not absolute_path.is_file():
            issues.append(
                _issue(
                    code="INT006",
                    message=f"Protected path is not a file: {file_path_value}",
                    severity="block",
                    recommendation="Restore expected protected file",
                    file_path=str(absolute_path),
                )
            )
            continue

        current_size = read_file_size(absolute_path)
        current_hash = compute_sha256(absolute_path)
        if current_size == size_value and current_hash == expected_hash:
            continue

        # MVP: Simplified handling - locked resources require unlock flow
        if resource_id_value in locked_resource_ids:
            issues.append(
                _issue(
                    code="AUTH001",
                    message=(
                        f"Locked resource `{file_path_value}` was modified. "
                        "Use `bpfw unlock` to authorize changes."
                    ),
                    severity="critical",
                    recommendation=f"Run `bpfw unlock {resource_id_value}` before editing, then `bpfw lock` when done",
                    file_path=str(absolute_path),
                )
            )
            continue

        issues.append(
            _issue(
                code="INT007",
                message=f"Protected file changed: {file_path_value}",
                severity="block",
                recommendation="Revert external change or run authorized flow and regenerate manifest",
                file_path=str(absolute_path),
            )
        )

    return checked_files, issues


def verify_integrity(project_root: Path) -> IntegrityVerificationResult:
    """Verify project integrity from signed manifest."""

    current_manifest_path = manifest_path(project_root=project_root)
    try:
        manifest_payload = load_manifest(project_root=project_root)
    except IntegrityManifestError as error:
        return IntegrityVerificationResult(
            is_valid=False,
            manifest_path=str(current_manifest_path),
            checked_files=0,
            issues=[
                _issue(
                    code="INT002",
                    message=str(error),
                    severity="block",
                    recommendation="Generate manifest with `bpfw init`",
                    file_path=str(current_manifest_path),
                )
            ],
        )

    shape_issues = _validate_manifest_shape(manifest_payload=manifest_payload, manifest_file_path=current_manifest_path)
    if shape_issues:
        return IntegrityVerificationResult(
            is_valid=False,
            manifest_path=str(current_manifest_path),
            checked_files=0,
            issues=shape_issues,
        )

    signature_issues = _verify_manifest_signature(manifest_payload=manifest_payload, manifest_file_path=current_manifest_path)
    if signature_issues:
        return IntegrityVerificationResult(
            is_valid=False,
            manifest_path=str(current_manifest_path),
            checked_files=0,
            issues=signature_issues,
        )

    # MVP: Skip approval verification (not in scope)
    coverage_issues = _validate_manifest_coverage(project_root=project_root, manifest_payload=manifest_payload)
    checked_files, file_issues = _verify_file_entries(
        project_root=project_root,
        manifest_payload=manifest_payload,
        locked_resource_ids=_locked_resource_ids(project_root=project_root),
    )
    issues = [
        *coverage_issues,
        *file_issues,
    ]

    return IntegrityVerificationResult(
        is_valid=not issues,
        manifest_path=str(current_manifest_path),
        checked_files=checked_files,
        issues=issues,
    )
