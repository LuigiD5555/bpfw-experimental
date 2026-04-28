from pathlib import Path

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


def _valid_blueprint_yaml() -> str:
    return """version: 1
project:
  name: demo
responsibilities: []
locked_resources: []
"""


def test_review_policy_blocks_when_architecture_validation_fails(tmp_path: Path) -> None:
    (tmp_path / "blueprint.yaml").write_text(_valid_blueprint_yaml(), encoding="utf-8")
    # Missing architecture.yaml should trigger architecture validation error.

    result = evaluate_review_policy(
        project_root=tmp_path,
        scope_resource_id="query_execution",
        allowed_files=["src/application/query/query_service.py"],
        forbidden_duplicates=[],
        diff_result=ReviewDiffResult(
            change_id="change-001",
            workspace_path=str(tmp_path / ".bpfw/workspaces/change-001"),
            file_changes=[_change("src/application/query/query_service.py")],
        ),
    )

    assert result.status == "BLOCK"
    assert any(finding.code == "ARCH001" for finding in result.findings)


def test_review_policy_blocks_when_duplication_detects_block(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "blueprint.yaml").write_text(_valid_blueprint_yaml(), encoding="utf-8")
    (tmp_path / "architecture.yaml").write_text(
        """profile_id: demo
layers:
  - layer_id: application
    paths:
      - src/application
rules: []
""",
        encoding="utf-8",
    )

    from bpfw.duplication.similarity_detector import DuplicationDetectionResult, DuplicationFinding
    import bpfw.review.policy as review_policy

    def _fake_duplication(project_root: Path) -> DuplicationDetectionResult:  # noqa: ARG001
        return DuplicationDetectionResult(
            findings=[
                DuplicationFinding(
                    code="DUP999",
                    severity="block",
                    message="Duplicated intent detected",
                    file_path="src/application/query/query_service.py",
                    symbol_name="QueryService",
                    responsibility_id="query_execution",
                    recommendation="Keep one implementation path",
                )
            ],
            scan_issues=[],
        )

    monkeypatch.setattr(review_policy, "detect_duplication", _fake_duplication)

    result = evaluate_review_policy(
        project_root=tmp_path,
        scope_resource_id="query_execution",
        allowed_files=["src/application/query/query_service.py"],
        forbidden_duplicates=[],
        diff_result=ReviewDiffResult(
            change_id="change-001",
            workspace_path=str(tmp_path / ".bpfw/workspaces/change-001"),
            file_changes=[_change("src/application/query/query_service.py")],
        ),
    )

    assert result.status == "BLOCK"
    assert any(finding.code == "DUP999" for finding in result.findings)
