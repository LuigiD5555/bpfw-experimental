from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from bpfw.core.registry import AcceptProposalStep, BlueprintCreateResponsibilityStep, DiscoverStep
from bpfw.core.result import ResultStatus
from bpfw.proposal.models import Proposal
from bpfw.proposal.resolver import ProposalResolutionError


def _context(project_root: Path, **arguments: str) -> SimpleNamespace:
    return SimpleNamespace(project_root=project_root, command_arguments=arguments)


def test_blueprint_create_responsibility_success_message(monkeypatch, tmp_path: Path) -> None:
    from bpfw.authority.change_engine import AuthorityChangeEngine

    def _fake_apply(self, project_root: Path, operation) -> None:  # noqa: ANN001
        del self, project_root, operation
        return None

    monkeypatch.setattr(AuthorityChangeEngine, "apply", _fake_apply)

    result = BlueprintCreateResponsibilityStep().run(
        _context(tmp_path, responsibility_id="query_execution", owner_layer="application")
    )
    assert result.status == ResultStatus.OK
    assert result.message == (
        "Responsibility created.\n"
        "Verify passed.\n"
        "Manifest updated."
    )


def test_discover_message_is_exact_for_single_proposal(monkeypatch, tmp_path: Path) -> None:
    from bpfw.core import registry as registry_module

    proposal = Proposal(
        proposal_id="proposal-retry-policy",
        source="discover",
        status="pending",
        detected_files=["src/application/query/retry_policy.py"],
        detected_symbols=[],
        suggested_responsibility="query_execution",
        suggested_action="add_to_existing_responsibility",
        risk="medium",
        reason=["x"],
        options=["reject"],
    )

    monkeypatch.setattr(registry_module, "scan_repository", lambda project_root: SimpleNamespace(findings=["raw"]))  # noqa: ARG005
    monkeypatch.setattr(registry_module, "classify_findings", lambda findings: [SimpleNamespace(severity="medium")])  # noqa: ARG005
    monkeypatch.setattr(registry_module, "build_proposals", lambda project_root, classified_findings: SimpleNamespace(created=[proposal]))  # noqa: ARG005
    monkeypatch.setattr(registry_module, "list_proposals", lambda project_root: [proposal])  # noqa: ARG005

    result = DiscoverStep().run(_context(tmp_path))
    assert result.status == ResultStatus.INFO
    assert result.message == (
        "Discovered undeclared file:\n"
        "src/application/query/retry_policy.py\n\n"
        "Suggested responsibility:\n"
        "query_execution\n\n"
        "Proposal created:\n"
        "proposal-retry-policy"
    )


def test_accept_proposal_success_message(monkeypatch, tmp_path: Path) -> None:
    from bpfw.core import registry as registry_module

    proposal = Proposal(
        proposal_id="proposal-retry-policy",
        source="discover",
        status="accepted",
        detected_files=["src/application/query/retry_policy.py"],
        detected_symbols=[],
        suggested_responsibility="query_execution",
        suggested_action="add_to_existing_responsibility",
        risk="medium",
        reason=["x"],
        options=["reject"],
    )
    resolved = SimpleNamespace(proposal=proposal, modified_blueprint=True)
    monkeypatch.setattr(registry_module, "accept_proposal", lambda **kwargs: resolved)

    result = AcceptProposalStep().run(_context(tmp_path, proposal_id="proposal-retry-policy"))
    assert result.status == ResultStatus.OK
    assert result.message == (
        "Proposal accepted.\n"
        "Blueprint updated mechanically.\n"
        "Verify passed.\n"
        "Manifest updated."
    )


def test_accept_proposal_block_message_when_authority_access_missing(monkeypatch, tmp_path: Path) -> None:
    from bpfw.core import registry as registry_module

    error = ProposalResolutionError(
        "BLOCK\n\n"
        "This proposal modifies blueprint.yaml.\n\n"
        "Required access:\n"
        "- resource: blueprint.yaml\n"
        "- scope: query_execution\n"
        "- operation: add_allowed_file"
    )
    monkeypatch.setattr(
        registry_module,
        "accept_proposal",
        lambda **kwargs: (_ for _ in ()).throw(error),
    )

    result = AcceptProposalStep().run(_context(tmp_path, proposal_id="proposal-retry-policy"))
    assert result.status == ResultStatus.BLOCK
    assert result.message == (
        "BLOCK\n\n"
        "This proposal modifies blueprint.yaml.\n\n"
        "Required access:\n"
        "- resource: blueprint.yaml\n"
        "- scope: query_execution\n"
        "- operation: add_allowed_file"
    )

