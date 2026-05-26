"""Authority Blueprint Engine for mechanical BPFW authority mutations."""

from pathlib import Path

from bpfw.core.blueprint_engine.models import (
    BlueprintChangePreview,
    BlueprintChangeRequest,
    BlueprintChangeResult,
)
from bpfw.core.blueprint_engine.planner import BlueprintPlanBuilder
from bpfw.core.blueprint_engine.safety import BlueprintEngineSafetyPolicy
from bpfw.core.authority.patch import AuthorityPatchEngine, PatchWriteContext
from bpfw.core.authority.patch.engine import PatchProgressCallback


class BlueprintEngine:
    """Apply approved mechanical changes to files under ``bpfw/``.

    This engine is intentionally mechanical. It does not detect drift and does
    not decide whether code or blueprint should win. It only applies approved
    requests produced by inspector, editor, planner, controlled refactors, or
    safe mechanical update detection.
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize the engine.

        Args:
            project_root: Project root directory.
        """
        self.project_root = project_root
        self._builder = BlueprintPlanBuilder()
        self._policy = BlueprintEngineSafetyPolicy()
        self._patch_engine = AuthorityPatchEngine(project_root=project_root)

    def preview_change(self, request: BlueprintChangeRequest) -> BlueprintChangePreview:
        """Preview one change request without writing.

        Args:
            request: Change request to preview.

        Returns:
            Structured preview with affected files or blocked reason.
        """
        return self.preview_changes([request])

    def preview_changes(self, requests: list[BlueprintChangeRequest]) -> BlueprintChangePreview:
        """Preview multiple change requests without writing.

        Args:
            requests: Change requests to preview.

        Returns:
            Structured preview with affected files or blocked reason.
        """
        blocked_reason = self._first_blocked_reason(requests)
        if blocked_reason is not None:
            return BlueprintChangePreview(allowed=False, blocked_reason=blocked_reason)

        plan = self._builder.build_plan(requests)
        patch_preview = self._patch_engine.preview(plan)
        validation_failed = bool(patch_preview.messages) and not patch_preview.modified_files
        blocked = patch_preview.error_message or ("\n".join(patch_preview.messages) if validation_failed else None)
        return BlueprintChangePreview(
            allowed=blocked is None,
            operation_count=plan.operation_count(),
            affected_files=tuple(sorted(plan.affected_files())),
            messages=tuple(patch_preview.messages),
            blocked_reason=blocked,
        )

    def apply_change(
        self,
        request: BlueprintChangeRequest,
        write_context: PatchWriteContext,
    ) -> BlueprintChangeResult:
        """Apply one approved change request.

        Args:
            request: Change request to apply.
            write_context: Explicit write permission context.

        Returns:
            Structured apply result.
        """
        return self.apply_changes([request], write_context=write_context)

    def apply_changes(
        self,
        requests: list[BlueprintChangeRequest],
        write_context: PatchWriteContext,
        progress_callback: PatchProgressCallback | None = None,
    ) -> BlueprintChangeResult:
        """Apply multiple approved requests as one patch plan.

        Args:
            requests: Change requests to apply.
            write_context: Explicit write permission context.
            progress_callback: Optional callback notified after patch operations progress.

        Returns:
            Structured apply result.
        """
        blocked_reason = self._first_blocked_reason(requests)
        if blocked_reason is not None:
            return BlueprintChangeResult(success=False, blocked_reason=blocked_reason)

        plan = self._builder.build_plan(requests)
        patch_result = self._patch_engine.apply(
            plan,
            write_context=write_context,
            progress_callback=progress_callback,
        )
        return BlueprintChangeResult(
            success=patch_result.success,
            patch_result=patch_result,
            messages=list(patch_result.messages),
            blocked_reason=patch_result.error_message,
        )

    def _first_blocked_reason(self, requests: list[BlueprintChangeRequest]) -> str | None:
        """Return the first policy violation for a request list.

        Args:
            requests: Change requests to validate.

        Returns:
            None when all requests are authorized, otherwise blocked reason.
        """
        for request in requests:
            blocked_reason = self._policy.validate_request(request)
            if blocked_reason is not None:
                return blocked_reason
        return None
