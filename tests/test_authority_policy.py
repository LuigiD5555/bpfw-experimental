from pathlib import Path

from bpfw.authority.policy import AuthorityPolicy


def test_non_authority_path_is_allowed(tmp_path: Path) -> None:
    decision = AuthorityPolicy().evaluate_direct_change(
        project_root=tmp_path,
        relative_path="src/application/query/query_service.py",
        operation=None,
        scope=None,
    )
    assert decision.allowed


def test_authority_without_operation_is_blocked(tmp_path: Path) -> None:
    decision = AuthorityPolicy().evaluate_direct_change(
        project_root=tmp_path,
        relative_path="blueprint.yaml",
        operation=None,
        scope="query_execution",
    )
    assert not decision.allowed
    assert decision.status == "BLOCK"


def test_authority_without_scope_is_blocked(tmp_path: Path) -> None:
    decision = AuthorityPolicy().evaluate_direct_change(
        project_root=tmp_path,
        relative_path="blueprint.yaml",
        operation="add_allowed_file",
        scope=None,
    )
    assert not decision.allowed
    assert decision.status == "BLOCK"


def test_authority_without_grant_is_blocked(tmp_path: Path) -> None:
    decision = AuthorityPolicy().evaluate_direct_change(
        project_root=tmp_path,
        relative_path="blueprint.yaml",
        operation="add_allowed_file",
        scope="query_execution",
    )
    assert not decision.allowed
    assert decision.status == "BLOCK"
