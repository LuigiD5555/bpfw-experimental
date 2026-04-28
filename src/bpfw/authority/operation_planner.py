from __future__ import annotations

from bpfw.authority.operation import AuthorityOperation
from bpfw.proposal.models import Proposal
from bpfw.proposal.models import SUGGESTED_ACTION_ADD_TO_EXISTING
from bpfw.proposal.models import SUGGESTED_ACTION_CREATE_NEW
from bpfw.proposal.models import SUGGESTED_ACTION_MARK_EXPERIMENTAL


class AuthorityOperationPlanner:
    """Builds authority operations from proposal acceptance intent."""

    def plan_from_proposal(self, proposal: Proposal, responsibility_id: str) -> list[AuthorityOperation]:
        operations: list[AuthorityOperation] = []
        for detected_file in proposal.detected_files:
            operations.append(
                AuthorityOperation(
                    operation_id=f"op-add-file-{proposal.proposal_id}-{responsibility_id}",
                    resource_id="project_blueprint",
                    resource_path="blueprint.yaml",
                    operation_type="add_allowed_file",
                    scope=responsibility_id,
                    payload={
                        "responsibility_id": responsibility_id,
                        "file_path": detected_file,
                    },
                )
            )
        return operations

    def plan_create_responsibility(self, proposal: Proposal, responsibility_id: str, canonical_name: str, owner_layer: str) -> list[AuthorityOperation]:
        return [
            AuthorityOperation(
                operation_id=f"op-create-responsibility-{proposal.proposal_id}-{responsibility_id}",
                resource_id="project_blueprint",
                resource_path="blueprint.yaml",
                operation_type="create_responsibility",
                scope=responsibility_id,
                payload={
                    "responsibility_id": responsibility_id,
                    "canonical_name": canonical_name,
                    "owner_layer": owner_layer,
                },
            )
        ]


class ProposalAuthorityPlanner:
    """Converts proposals into mechanical authority operations."""

    def __init__(self) -> None:
        self._operation_planner = AuthorityOperationPlanner()

    def plan_acceptance(
        self,
        proposal: Proposal,
        responsibility_id: str,
        suggested_action: str,
        canonical_name: str,
        owner_layer: str,
    ) -> list[AuthorityOperation]:
        if suggested_action == SUGGESTED_ACTION_CREATE_NEW:
            operations = self._operation_planner.plan_create_responsibility(
                proposal=proposal,
                responsibility_id=responsibility_id,
                canonical_name=canonical_name,
                owner_layer=owner_layer,
            )
            operations.extend(
                self._operation_planner.plan_from_proposal(
                    proposal=proposal,
                    responsibility_id=responsibility_id,
                )
            )
            return operations

        if suggested_action in {SUGGESTED_ACTION_ADD_TO_EXISTING, SUGGESTED_ACTION_MARK_EXPERIMENTAL}:
            operation_type = "add_allowed_file"
            if suggested_action == SUGGESTED_ACTION_MARK_EXPERIMENTAL:
                operation_type = "add_experimental_implementation"

            operations: list[AuthorityOperation] = []
            for detected_file in proposal.detected_files:
                operations.append(
                    AuthorityOperation(
                        operation_id=f"op-{operation_type}-{proposal.proposal_id}-{responsibility_id}",
                        resource_id="project_blueprint",
                        resource_path="blueprint.yaml",
                        operation_type=operation_type,
                        scope=responsibility_id,
                        payload={
                            "responsibility_id": responsibility_id,
                            "file_path": detected_file,
                        },
                    )
                )
            return operations

        raise RuntimeError(f"Unsupported suggested action `{suggested_action}`")
