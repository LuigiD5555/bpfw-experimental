"""Policy evaluation for workspace review decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bpfw.change.scope import build_locked_resource_index
from bpfw.review.diff import FileChange, ReviewDiffResult
from bpfw.review.structural_diff import detect_suspicious_new_files


@dataclass(slots=True, frozen=True)
class PolicyFinding:
    """Policy-level finding for review decision."""

    code: str
    severity: str
    message: str
    file_path: str
    recommendation: str


@dataclass(slots=True)
class PolicyEvaluationResult:
    """Policy evaluation summary."""

    status: str
    findings: list[PolicyFinding] = field(default_factory=list)



def _finding(code: str, severity: str, message: str, file_path: str, recommendation: str) -> PolicyFinding:
    return PolicyFinding(
        code=code,
        severity=severity,
        message=message,
        file_path=file_path,
        recommendation=recommendation,
    )


def evaluate_review_policy(
    *,
    project_root: Path,
    scope_resource_id: str,
    allowed_files: list[str],
    forbidden_duplicates: list[str],
    diff_result: ReviewDiffResult,
) -> PolicyEvaluationResult:
    """Evaluate policy rules for one workspace diff."""

    locked_index = build_locked_resource_index(project_root=project_root)
    allowed_paths = set(allowed_files)
    findings: list[PolicyFinding] = []

    for file_change in diff_result.file_changes:
        if file_change.path in locked_index.by_path and locked_index.by_path[file_change.path] != scope_resource_id:
            findings.append(
                _finding(
                    code="RV011",
                    severity="block",
                    message=(
                        f"Locked resource `{file_change.path}` cannot be changed from scope `{scope_resource_id}`"
                    ),
                    file_path=file_change.path,
                    recommendation="Request approval through the locked resource flow",
                )
            )
            continue

        if file_change.path not in allowed_paths:
            findings.append(
                _finding(
                    code="RV008",
                    severity="block",
                    message=f"File `{file_change.path}` is outside the declared scope",
                    file_path=file_change.path,
                    recommendation="Limit changes to files declared in scope allowed_files",
                )
            )

    structural_findings = detect_suspicious_new_files(
        file_changes=diff_result.file_changes,
        forbidden_duplicates=forbidden_duplicates,
    )
    for structural_finding in structural_findings:
        findings.append(
            _finding(
                code=structural_finding.code,
                severity="block",
                message=structural_finding.message,
                file_path=structural_finding.file_path,
                recommendation=structural_finding.recommendation,
            )
        )

    if findings:
        requires_approval = any(finding.code == "RV011" for finding in findings)
        return PolicyEvaluationResult(status="REQUIRES_APPROVAL" if requires_approval else "BLOCK", findings=findings)

    return PolicyEvaluationResult(status="ALLOW", findings=[])
