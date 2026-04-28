from __future__ import annotations

from bpfw.authority.operation import AuthorityOperation
from bpfw.blueprint.models import BlueprintModel
from bpfw.blueprint.models import BlueprintResponsibility
from bpfw.lifecycle.states import OFFICIAL_STATES
from bpfw.lifecycle.transition_policy import can_be_active_by_default


class BlueprintMutationError(RuntimeError):
    """Raised when a mechanical blueprint mutation is invalid."""


class BlueprintMutator:
    """Applies mechanical blueprint operations to a loaded blueprint model."""

    def apply(self, blueprint: BlueprintModel, operation: AuthorityOperation) -> BlueprintModel:
        if operation.operation_type == "add_allowed_file":
            return self.add_allowed_file(
                blueprint=blueprint,
                responsibility_id=operation.payload.get("responsibility_id", operation.scope),
                file_path=operation.payload.get("file_path", ""),
            )
        if operation.operation_type == "add_allowed_symbol":
            return self.add_allowed_symbol(
                blueprint=blueprint,
                responsibility_id=operation.payload.get("responsibility_id", operation.scope),
                symbol_name=operation.payload.get("symbol_name", ""),
            )
        if operation.operation_type == "create_responsibility":
            return self.create_responsibility(
                blueprint=blueprint,
                responsibility_id=operation.payload.get("responsibility_id", ""),
                canonical_name=operation.payload.get("canonical_name", ""),
                owner_layer=operation.payload.get("owner_layer", ""),
            )
        if operation.operation_type == "set_lifecycle":
            return self.set_lifecycle(
                blueprint=blueprint,
                component_id=operation.payload.get("component_id", ""),
                lifecycle_state=operation.payload.get("lifecycle_state", ""),
            )
        raise BlueprintMutationError(f"Unsupported blueprint operation: {operation.operation_type}")

    def add_allowed_file(self, blueprint: BlueprintModel, responsibility_id: str, file_path: str) -> BlueprintModel:
        if not responsibility_id:
            raise BlueprintMutationError("Missing responsibility_id for add_allowed_file")
        if not file_path or file_path.startswith("/") or ".." in file_path.split("/"):
            raise BlueprintMutationError("file_path must be repo-relative and cannot escape project root")
        for responsibility in blueprint.responsibilities:
            if responsibility.responsibility_id != responsibility_id:
                continue
            if file_path not in responsibility.allowed_files:
                responsibility.allowed_files.append(file_path)
            return blueprint
        raise BlueprintMutationError(f"Responsibility `{responsibility_id}` was not found in blueprint")

    def add_allowed_symbol(self, blueprint: BlueprintModel, responsibility_id: str, symbol_name: str) -> BlueprintModel:
        if not responsibility_id:
            raise BlueprintMutationError("Missing responsibility_id for add_allowed_symbol")
        if not symbol_name:
            raise BlueprintMutationError("Missing symbol_name for add_allowed_symbol")
        for responsibility in blueprint.responsibilities:
            if responsibility.responsibility_id == responsibility_id and symbol_name not in responsibility.allowed_symbols:
                responsibility.allowed_symbols.append(symbol_name)
                return blueprint
        raise BlueprintMutationError(f"Responsibility `{responsibility_id}` was not found in blueprint")

    def create_responsibility(self, blueprint: BlueprintModel, responsibility_id: str, canonical_name: str, owner_layer: str) -> BlueprintModel:
        if not responsibility_id:
            raise BlueprintMutationError("Missing responsibility_id for create_responsibility")
        if not canonical_name:
            raise BlueprintMutationError("Missing canonical_name for create_responsibility")
        if owner_layer not in {"application", "domain", "infrastructure", "bootstrap", "public"}:
            raise BlueprintMutationError(f"Invalid owner_layer `{owner_layer}`")
        if any(item.responsibility_id == responsibility_id for item in blueprint.responsibilities):
            raise BlueprintMutationError(f"Responsibility `{responsibility_id}` already exists")
        blueprint.responsibilities.append(
            BlueprintResponsibility(
                responsibility_id=responsibility_id,
                canonical_name=canonical_name,
                owner_layer=owner_layer,
                lifecycle_state="planned",
                allowed_files=[],
                allowed_symbols=[],
                allowed_implementations=[],
                active_implementation="",
                forbidden_duplicates=[],
                mutability="editable",
                owner="project_owner",
            )
        )
        return blueprint

    def set_lifecycle(self, blueprint: BlueprintModel, component_id: str, lifecycle_state: str) -> BlueprintModel:
        if not component_id:
            raise BlueprintMutationError("Missing component_id for set_lifecycle")
        if lifecycle_state not in OFFICIAL_STATES:
            raise BlueprintMutationError(f"Invalid lifecycle_state `{lifecycle_state}`")
        for responsibility in blueprint.responsibilities:
            if responsibility.responsibility_id != component_id:
                continue
            if lifecycle_state == "active":
                decision = can_be_active_by_default(lifecycle_state)
                if not decision.allowed:
                    raise BlueprintMutationError(decision.message or "Lifecycle transition is not allowed")
            responsibility.lifecycle_state = lifecycle_state
            return blueprint
        raise BlueprintMutationError(f"Responsibility `{component_id}` was not found in blueprint")
