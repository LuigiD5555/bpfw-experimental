from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from bpfw.access.verifier import AccessVerifier
from bpfw.authority.audit import AuthorityAuditLog
from bpfw.authority.lock_manager import AuthorityLockManager
from bpfw.authority.operation import AuthorityOperation
from bpfw.authority.resources import AuthorityResourceRegistry
from bpfw.authority.state import clear_unlock_window, load_authority_state
from bpfw.blueprint.mutator import BlueprintMutator
from bpfw.blueprint.validator import validate_blueprint
from bpfw.blueprint.writer import BlueprintWriter
from bpfw.core.result import ResultStatus
from bpfw.integrity.manifest import write_manifest


class AuthorityChangeEngine:
    """Applies authorized mechanical changes to authority resources."""

    def __init__(self) -> None:
        self._access_verifier = AccessVerifier()
        self._registry = AuthorityResourceRegistry()
        self._mutator = BlueprintMutator()
        self._writer = BlueprintWriter()
        self._audit = AuthorityAuditLog()

    def _require_unlock_window(self, project_root: Path, operation: AuthorityOperation) -> None:
        state = load_authority_state(project_root=project_root)
        window = state.active_unlock_window
        if window is None:
            raise RuntimeError(
                "BLOCK\n\n"
                "No active authority unlock window was found.\n\n"
                "Run:\n"
                "bpfw authority unlock <resource> --scope <scope> --operation <operation> --ttl <duration> --reason <reason>"
            )
        if window.resource_id != operation.resource_id:
            raise RuntimeError("Unlock window resource does not match authority operation resource.")
        if window.scope != operation.scope:
            raise RuntimeError("Unlock window scope does not match authority operation scope.")
        if window.operation != operation.operation_type:
            raise RuntimeError("Unlock window operation does not match authority operation type.")

        expires_at = datetime.fromisoformat(window.expires_at.replace("Z", "+00:00"))
        now_utc = datetime.now(tz=timezone.utc)
        if expires_at.astimezone(timezone.utc) <= now_utc:
            raise RuntimeError("Unlock window has expired. Run authority unlock again.")

    def _verify_grant(self, project_root: Path, operation: AuthorityOperation):  # noqa: ANN001
        verification = self._access_verifier.verify(
            project_root=project_root,
            resource_id=operation.resource_id,
            operation=operation.operation_type,
            scope=operation.scope,
        )
        if not verification.valid or not verification.grant_id:
            raise RuntimeError(verification.reason)
        return verification

    def _apply_operation(self, project_root: Path, operation: AuthorityOperation) -> None:
        validation_result = validate_blueprint(project_root=project_root)
        if not validation_result.is_valid or validation_result.blueprint is None:
            raise RuntimeError(validation_result.errors[0].message)

        mutated_blueprint = self._mutator.apply(blueprint=validation_result.blueprint, operation=operation)
        self._writer.write(project_root=project_root, blueprint=mutated_blueprint)

        post_validation_result = validate_blueprint(project_root=project_root)
        if not post_validation_result.is_valid:
            raise RuntimeError(post_validation_result.errors[0].message)

    def _verify_pipeline(self, project_root: Path) -> None:
        from bpfw.core.engine import BlueprintEngine, build_command

        verify_result = BlueprintEngine().run(build_command("verify", project_root=project_root, arguments={}))
        if verify_result.status in {ResultStatus.BLOCK, ResultStatus.CRITICAL}:
            blocking_step = next(
                (step for step in verify_result.steps if step.status in {ResultStatus.BLOCK, ResultStatus.CRITICAL}),
                verify_result.steps[0],
            )
            raise RuntimeError(blocking_step.message)

    def _relock_after_operation(self, project_root: Path, resource_id: str) -> None:
        lock_manager = AuthorityLockManager()
        lock_manager.lock_resource(project_root=project_root, resource_id=resource_id)
        clear_unlock_window(project_root=project_root, mark_locked=True)

    def apply(self, project_root: Path, operation: AuthorityOperation) -> None:
        resource = self._registry.get(operation.resource_id)
        if resource is None:
            raise RuntimeError(f"Unknown authority resource: {operation.resource_id}")

        self._require_unlock_window(project_root=project_root, operation=operation)
        verification = self._verify_grant(project_root=project_root, operation=operation)

        try:
            self._apply_operation(project_root=project_root, operation=operation)
            self._verify_pipeline(project_root=project_root)
            write_manifest(project_root=project_root)
            self._audit.record(project_root=project_root, operation=operation, grant_id=verification.grant_id)
        finally:
            self._relock_after_operation(project_root=project_root, resource_id=operation.resource_id)

    def apply_many(self, project_root: Path, operations: list[AuthorityOperation]) -> None:
        if not operations:
            return

        first_operation = operations[0]
        resource = self._registry.get(first_operation.resource_id)
        if resource is None:
            raise RuntimeError(f"Unknown authority resource: {first_operation.resource_id}")

        self._require_unlock_window(project_root=project_root, operation=first_operation)
        verification = self._verify_grant(project_root=project_root, operation=first_operation)

        for operation in operations:
            if operation.resource_id != first_operation.resource_id:
                raise RuntimeError("All authority operations in one batch must target the same resource.")
            if operation.scope != first_operation.scope:
                raise RuntimeError("All authority operations in one batch must use the same scope.")

        try:
            for operation in operations:
                self._apply_operation(project_root=project_root, operation=operation)
            self._verify_pipeline(project_root=project_root)
            write_manifest(project_root=project_root)
            for operation in operations:
                self._audit.record(project_root=project_root, operation=operation, grant_id=verification.grant_id)
        finally:
            self._relock_after_operation(project_root=project_root, resource_id=first_operation.resource_id)
