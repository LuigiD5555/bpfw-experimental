from pathlib import Path

from bpfw.review.authority_diff import AuthorityDiffChecker
from bpfw.review.diff import FileChange, ReviewDiffResult
from bpfw.review.policy import evaluate_review_policy


def _change(path: str) -> FileChange:
    return FileChange(
        path=path,
        change_type="modified",
        declared_in_scope=True,
        repo_exists=True,
        workspace_exists=True,
        repo_sha256="a",
        workspace_sha256="b",
        repo_size=1,
        workspace_size=2,
    )


def test_authority_diff_checker_detects_blueprint_yaml() -> None:
    findings = AuthorityDiffChecker().check([_change("blueprint.yaml")])
    assert len(findings) == 1
    assert findings[0].resource_id == "project_blueprint"
    assert findings[0].severity == "block"


def test_review_policy_blocks_manual_authority_diff(tmp_path: Path) -> None:
    (tmp_path / "blueprint.yaml").write_text(
        """version: 1
project:
  name: demo
responsibilities: []
locked_resources: []
""",
        encoding="utf-8",
    )

    diff_result = ReviewDiffResult(
        change_id="change-001",
        workspace_path=str(tmp_path / ".bpfw/workspaces/change-001"),
        file_changes=[_change("blueprint.yaml")],
    )

    result = evaluate_review_policy(
        project_root=tmp_path,
        scope_resource_id="query_execution",
        allowed_files=["blueprint.yaml"],
        forbidden_duplicates=[],
        diff_result=diff_result,
    )

    assert result.status == "BLOCK"
    assert result.findings
    assert result.findings[0].code == "RV012"
    assert "authority resource" in result.findings[0].message
    assert "Direct authority edits are not allowed" in result.findings[0].message
