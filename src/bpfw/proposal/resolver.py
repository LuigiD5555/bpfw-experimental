"""Resolve accept/reject actions for discover proposals."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from bpfw.authority.change_engine import AuthorityChangeEngine
from bpfw.authority.operation_planner import AuthorityOperationPlanner
from bpfw.blueprint.loader import load_blueprint_data
from bpfw.blueprint.validator import validate_blueprint
from bpfw.proposal.models import (
    PROPOSAL_STATUS_ACCEPTED,
    PROPOSAL_STATUS_PENDING,
    PROPOSAL_STATUS_REJECTED,
    REJECT_ACTION_MOVE,
    REJECT_ACTION_SUGGEST_DELETE,
    REJECT_ACTION_UNTRACKED,
    SUGGESTED_ACTION_ADD_TO_EXISTING,
    SUGGESTED_ACTION_CREATE_NEW,
    Proposal,
)
from bpfw.proposal.store import ProposalStoreError, load_proposal, save_proposal


REJECTED_RELATIVE_DIR = ".bpfw/rejected"


class ProposalResolutionError(RuntimeError):
    """Raised when a proposal cannot be accepted/rejected safely."""


@dataclass(slots=True)
class ProposalResolutionResult:
    """Outcome metadata after proposal resolution."""

    proposal: Proposal
    modified_blueprint: bool
    moved_files: list[str]



def _to_canonical_name(identifier: str) -> str:
    tokens = [token for token in identifier.strip().split("_") if token]
    if not tokens:
        return "GeneratedResponsibility"
    return "".join(token[:1].upper() + token[1:] for token in tokens)



def _to_implementation_id(base_name: str, state: str) -> str:
    normalized = "_".join(token for token in base_name.strip().lower().split("_") if token)
    if not normalized:
        normalized = "generated"
    return f"{normalized}_{state}"



def _read_blueprint_payload(project_root: Path) -> tuple[Path, dict]:
    try:
        blueprint_path, payload = load_blueprint_data(project_root=project_root)
    except Exception as error:  # noqa: BLE001
        raise ProposalResolutionError(str(error)) from error

    if not isinstance(payload.get("responsibilities"), list):
        raise ProposalResolutionError("blueprint.yaml field `responsibilities` must be a list")
    return blueprint_path, payload



def _write_blueprint_payload(blueprint_path: Path, payload: dict) -> None:
    blueprint_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")



def _ensure_pending(proposal: Proposal) -> None:
    if proposal.status != PROPOSAL_STATUS_PENDING:
        raise ProposalResolutionError(f"Proposal `{proposal.proposal_id}` is not pending")



def _find_responsibility(payload: dict, responsibility_id: str) -> dict | None:
    responsibilities = payload.get("responsibilities", [])
    for responsibility in responsibilities:
        if not isinstance(responsibility, dict):
            continue
        if str(responsibility.get("responsibility_id", "")).strip() == responsibility_id:
            return responsibility
    return None



def _append_unique_string(items: list[str], value: str) -> list[str]:
    if value and value not in items:
        items.append(value)
    return items



def _class_symbol_names(proposal: Proposal) -> list[str]:
    class_names: list[str] = []
    for finding in proposal.findings:
        if finding.symbol_type != "class":
            continue
        if finding.symbol_name and finding.symbol_name not in class_names:
            class_names.append(finding.symbol_name)
    return class_names



def _add_to_existing_responsibility(
    payload: dict,
    proposal: Proposal,
    responsibility_id: str,
    state: str,
) -> None:
    responsibility = _find_responsibility(payload=payload, responsibility_id=responsibility_id)
    if responsibility is None:
        raise ProposalResolutionError(f"Responsibility `{responsibility_id}` was not found in blueprint")

    allowed_files = responsibility.get("allowed_files", [])
    if not isinstance(allowed_files, list):
        allowed_files = []
    for file_path in proposal.detected_files:
        _append_unique_string(allowed_files, file_path)
    responsibility["allowed_files"] = allowed_files

    allowed_symbols = responsibility.get("allowed_symbols", [])
    if not isinstance(allowed_symbols, list):
        allowed_symbols = []
    for symbol in proposal.detected_symbols:
        _append_unique_string(allowed_symbols, symbol)
    responsibility["allowed_symbols"] = allowed_symbols

    allowed_implementations = responsibility.get("allowed_implementations", [])
    if not isinstance(allowed_implementations, list):
        allowed_implementations = []

    existing_implementation_ids = {
        str(item.get("implementation_id", ""))
        for item in allowed_implementations
        if isinstance(item, dict)
    }

    class_names = _class_symbol_names(proposal=proposal)
    target_lifecycle_state = "experimental" if state == "experimental" else "planned"
    for class_name in class_names:
        implementation_id = _to_implementation_id(base_name=class_name, state=target_lifecycle_state)
        if implementation_id in existing_implementation_ids:
            continue
        implementation_file = proposal.detected_files[0] if proposal.detected_files else ""
        allowed_implementations.append(
            {
                "implementation_id": implementation_id,
                "class_name": class_name,
                "file": implementation_file,
                "lifecycle_state": target_lifecycle_state,
                "replacement_id": responsibility.get("active_implementation", "") or None,
                "disabled_reason": None,
                "removal_plan": None,
            }
        )
        existing_implementation_ids.add(implementation_id)

    responsibility["allowed_implementations"] = allowed_implementations



def _create_new_responsibility(
    payload: dict,
    proposal: Proposal,
    new_responsibility_id: str,
    state: str,
) -> None:
    responsibilities = payload.get("responsibilities", [])

    if _find_responsibility(payload=payload, responsibility_id=new_responsibility_id) is not None:
        raise ProposalResolutionError(f"Responsibility `{new_responsibility_id}` already exists")

    responsibility_layer = "application"
    if proposal.detected_files:
        first_file = proposal.detected_files[0]
        file_parts = Path(first_file).parts
        if len(file_parts) >= 2 and file_parts[0] == "src":
            responsibility_layer = file_parts[1]

    lifecycle_state = "experimental" if state == "experimental" else "active"
    class_names = _class_symbol_names(proposal=proposal)
    if class_names:
        implementation_class = class_names[0]
    else:
        implementation_class = _to_canonical_name(new_responsibility_id)

    implementation_id = _to_implementation_id(base_name=new_responsibility_id, state=lifecycle_state)
    implementation_file = proposal.detected_files[0] if proposal.detected_files else ""

    responsibility_payload = {
        "responsibility_id": new_responsibility_id,
        "canonical_name": _to_canonical_name(new_responsibility_id),
        "owner_layer": responsibility_layer,
        "lifecycle_state": lifecycle_state,
        "allowed_files": list(proposal.detected_files),
        "allowed_symbols": list(proposal.detected_symbols),
        "allowed_implementations": [
            {
                "implementation_id": implementation_id,
                "class_name": implementation_class,
                "file": implementation_file,
                "lifecycle_state": lifecycle_state,
                "replacement_id": None,
                "disabled_reason": None,
                "removal_plan": None,
            }
        ],
        "active_implementation": implementation_id,
        "forbidden_duplicates": [],
        "mutability": "editable",
        "owner": "project_owner",
    }

    responsibilities.append(responsibility_payload)
    payload["responsibilities"] = responsibilities



def _validate_blueprint_after_write(project_root: Path) -> None:
    validation_result = validate_blueprint(project_root=project_root)
    if validation_result.is_valid:
        return
    first_error = validation_result.errors[0]
    raise ProposalResolutionError(
        f"Blueprint validation failed after proposal accept: {first_error.message}"
    )



def accept_proposal(
    project_root: Path,
    proposal_id: str,
    responsibility_id: str = "",
    new_responsibility_id: str = "",
    state: str = "",
) -> ProposalResolutionResult:
    """Accept one pending proposal and update blueprint accordingly."""

    try:
        proposal = load_proposal(project_root=project_root, proposal_id=proposal_id)
    except ProposalStoreError as error:
        raise ProposalResolutionError(str(error)) from error

    _ensure_pending(proposal=proposal)

    normalized_state = state.strip().lower()
    if normalized_state and normalized_state not in {"planned", "active", "experimental", "disabled", "deprecated", "legacy"}:
        raise ProposalResolutionError("Invalid --state value")

    if new_responsibility_id.strip():
        selected_action = SUGGESTED_ACTION_CREATE_NEW
    elif responsibility_id.strip():
        selected_action = SUGGESTED_ACTION_ADD_TO_EXISTING
    else:
        selected_action = proposal.suggested_action or SUGGESTED_ACTION_ADD_TO_EXISTING

    _read_blueprint_payload(project_root=project_root)
    modified_blueprint = False
    operation_list = []

    try:
        planner = AuthorityOperationPlanner()
        if selected_action != SUGGESTED_ACTION_CREATE_NEW:
            target_responsibility = responsibility_id.strip() or proposal.suggested_responsibility.strip()
            if not target_responsibility:
                raise ProposalResolutionError(
                    "Missing target responsibility. Use --responsibility or --as-new-responsibility"
                )
            operation_list = planner.plan_from_proposal(
                proposal=proposal,
                responsibility_id=target_responsibility,
            )
            modified_blueprint = True
            AuthorityChangeEngine().apply_many(project_root=project_root, operations=operation_list)
        else:
            target_new_responsibility = new_responsibility_id.strip() or proposal.suggested_responsibility.strip()
            if not target_new_responsibility:
                first_file_name = Path(proposal.detected_files[0]).stem if proposal.detected_files else proposal.proposal_id
                target_new_responsibility = first_file_name.replace("-", "_")
            canonical_name = _to_canonical_name(target_new_responsibility)
            owner_layer = "application"
            if proposal.detected_files:
                file_parts = Path(proposal.detected_files[0]).parts
                if len(file_parts) >= 2 and file_parts[0] == "src":
                    owner_layer = file_parts[1]
            operation_list = planner.plan_create_responsibility(
                proposal=proposal,
                responsibility_id=target_new_responsibility,
                canonical_name=canonical_name,
                owner_layer=owner_layer,
            )
            operation_list.extend(planner.plan_from_proposal(proposal=proposal, responsibility_id=target_new_responsibility))
            modified_blueprint = True
            AuthorityChangeEngine().apply_many(project_root=project_root, operations=operation_list)
    except Exception as error:  # noqa: BLE001
        if isinstance(error, ProposalResolutionError):
            raise
        if operation_list:
            first_operation = operation_list[0]
            raise ProposalResolutionError(
                "BLOCK\n\n"
                "This proposal requires authority access.\n\n"
                "Required:\n"
                f"- resource: {first_operation.resource_path}\n"
                f"- scope: {first_operation.scope}\n"
                f"- operation: {first_operation.operation_type}\n\n"
                "Run:\n"
                "bpfw access request blueprint "
                f"--scope {first_operation.scope} "
                f"--operation {first_operation.operation_type} "
                f"--reason \"Accept {proposal.proposal_id}\""
            ) from error
        raise ProposalResolutionError(str(error)) from error

    proposal.status = PROPOSAL_STATUS_ACCEPTED
    proposal.resolution = {
        "action": selected_action,
        "responsibility_id": responsibility_id.strip(),
        "new_responsibility_id": new_responsibility_id.strip(),
        "state": normalized_state,
    }

    try:
        save_proposal(project_root=project_root, proposal=proposal)
    except ProposalStoreError as error:
        raise ProposalResolutionError(str(error)) from error

    return ProposalResolutionResult(proposal=proposal, modified_blueprint=modified_blueprint, moved_files=[])



def _rejected_path(project_root: Path, proposal_id: str, file_path: str) -> Path:
    return project_root / REJECTED_RELATIVE_DIR / proposal_id / file_path



def reject_proposal(project_root: Path, proposal_id: str, action: str = REJECT_ACTION_MOVE) -> ProposalResolutionResult:
    """Reject one proposal and apply configured file disposition."""

    normalized_action = action.strip() or REJECT_ACTION_MOVE
    if normalized_action not in {REJECT_ACTION_MOVE, REJECT_ACTION_UNTRACKED, REJECT_ACTION_SUGGEST_DELETE}:
        raise ProposalResolutionError("Invalid reject action")

    try:
        proposal = load_proposal(project_root=project_root, proposal_id=proposal_id)
    except ProposalStoreError as error:
        raise ProposalResolutionError(str(error)) from error

    _ensure_pending(proposal=proposal)

    moved_files: list[str] = []
    if normalized_action == REJECT_ACTION_MOVE:
        for detected_file in proposal.detected_files:
            source_path = project_root / detected_file
            if not source_path.exists() or not source_path.is_file():
                continue
            destination_path = _rejected_path(project_root=project_root, proposal_id=proposal.proposal_id, file_path=detected_file)
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source_path), str(destination_path))
            moved_files.append(str(destination_path.resolve().relative_to(project_root.resolve())))

    proposal.status = PROPOSAL_STATUS_REJECTED
    proposal.resolution = {
        "action": "reject",
        "reject_action": normalized_action,
    }
    if normalized_action == REJECT_ACTION_SUGGEST_DELETE:
        proposal.reason.append("Suggested deletion after rejection")

    try:
        save_proposal(project_root=project_root, proposal=proposal)
    except ProposalStoreError as error:
        raise ProposalResolutionError(str(error)) from error

    return ProposalResolutionResult(proposal=proposal, modified_blueprint=False, moved_files=moved_files)
