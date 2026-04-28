from __future__ import annotations

from pathlib import Path

from bpfw.access.verifier import AccessVerifier
from bpfw.authority.audit import AuthorityAuditLog
from bpfw.authority.operation import AuthorityOperation
from bpfw.authority.resources import AuthorityResourceRegistry
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

    def apply(self, project_root: Path, operation: AuthorityOperation) -> None:
        resource = self._registry.get(operation.resource_id)
        if resource is None:
            raise RuntimeError(f"Unknown authority resource: {operation.resource_id}")
        verification = self._access_verifier.verify(
            project_root=project_root,
            resource_id=operation.resource_id,
            operation=operation.operation_type,
            scope=operation.scope,
        )
        if not verification.valid or not verification.grant_id:
            raise RuntimeError(verification.reason)

        validation_result = validate_blueprint(project_root=project_root)
        if not validation_result.is_valid or validation_result.blueprint is None:
            raise RuntimeError(validation_result.errors[0].message)

        mutated_blueprint = self._mutator.apply(blueprint=validation_result.blueprint, operation=operation)
        self._writer.write(project_root=project_root, blueprint=mutated_blueprint)

        post_validation_result = validate_blueprint(project_root=project_root)
        if not post_validation_result.is_valid:
            raise RuntimeError(post_validation_result.errors[0].message)

        from bpfw.core.engine import BlueprintEngine, build_command

        verify_result = BlueprintEngine().run(build_command("verify", project_root=project_root, arguments={}))
        if verify_result.status in {ResultStatus.BLOCK, ResultStatus.CRITICAL}:
            blocking_step = next(
                (step for step in verify_result.steps if step.status in {ResultStatus.BLOCK, ResultStatus.CRITICAL}),
                verify_result.steps[0],
            )
            raise RuntimeError(blocking_step.message)

        write_manifest(project_root=project_root)
        self._audit.record(project_root=project_root, operation=operation, grant_id=verification.grant_id)

    def apply_many(self, project_root: Path, operations: list[AuthorityOperation]) -> None:
        blueprint_path = project_root / "blueprint.yaml"
        original_blueprint_text = blueprint_path.read_text(encoding="utf-8") if blueprint_path.exists() else ""
        try:
            for operation in operations:
                self.apply(project_root=project_root, operation=operation)
        except Exception:
            if blueprint_path.exists():
                blueprint_path.write_text(original_blueprint_text, encoding="utf-8")
            raise
