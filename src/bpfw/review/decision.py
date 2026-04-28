"""High-level review decision orchestrator for change sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bpfw.change.session import ChangeSession, ChangeSessionError, load_change_session
from bpfw.review.diff import FileChange, ReviewDiffResult, compute_review_diff
from bpfw.review.policy import PolicyEvaluationResult, PolicyFinding, evaluate_review_policy


class ReviewDecisionError(RuntimeError):
    """Raised when review decision cannot be produced."""


@dataclass(slots=True)
class ReviewDecisionResult:
    """Review decision output consumed by CLI and apply flow."""

    change_id: str
    status: str
    diff: ReviewDiffResult
    policy: PolicyEvaluationResult
    findings: list[PolicyFinding] = field(default_factory=list)



def execute_review(project_root: Path, change_id: str) -> ReviewDecisionResult:
    """Execute review for a persisted change session."""

    try:
        session = load_change_session(project_root=project_root, change_id=change_id)
    except ChangeSessionError as error:
        raise ReviewDecisionError(str(error)) from error

    return review_session(project_root=project_root, session=session)


def review_session(project_root: Path, session: ChangeSession) -> ReviewDecisionResult:
    """Execute review policy for loaded session."""

    diff_result = compute_review_diff(project_root=project_root, session=session)
    policy_result = evaluate_review_policy(
        project_root=project_root,
        scope_resource_id=session.scope_resource_id,
        allowed_files=session.allowed_files,
        forbidden_duplicates=session.forbidden_duplicates,
        diff_result=diff_result,
    )

    return ReviewDecisionResult(
        change_id=session.change_id,
        status=policy_result.status,
        diff=diff_result,
        policy=policy_result,
        findings=list(policy_result.findings),
    )


def primary_finding(findings: list[PolicyFinding]) -> PolicyFinding | None:
    """Return first deterministic finding for message rendering."""

    if not findings:
        return None
    return findings[0]


def changed_paths(file_changes: list[FileChange]) -> list[str]:
    """Extract changed paths from diff result."""

    return [item.path for item in file_changes]
