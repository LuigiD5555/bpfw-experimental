from __future__ import annotations

from bpfw.authority.operation import AuthorityOperation
from bpfw.proposal.models import Proposal


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
