"""PURPOSE authority Blueprint Engine for file-change BPFW authority mutations
DOMAIN  approved blueprint changes
"""

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
    """PURPOSE apply approved approved file changes to files under bpfw/
        DOMAIN  approved blueprint changes
        """

    def __init__(self, project_root: Path) -> None:
        """PURPOSE set up the engine
        DOMAIN  approved blueprint changes
        """
        self.project_root = project_root
        self._builder = BlueprintPlanBuilder()
        self._policy = BlueprintEngineSafetyPolicy()
        self._patch_engine = AuthorityPatchEngine(project_root=project_root)

    def preview_change(self, request: BlueprintChangeRequest) -> BlueprintChangePreview:
        """PURPOSE preview one change request without writing
        DOMAIN  approved blueprint changes
        """
        return self.preview_changes([request])

    def preview_changes(self, requests: list[BlueprintChangeRequest]) -> BlueprintChangePreview:
        """PURPOSE preview multiple change requests without writing
        DOMAIN  approved blueprint changes
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
        """PURPOSE apply one approved change request
        DOMAIN  approved blueprint changes
        """
        return self.apply_changes([request], write_context=write_context)

    def apply_changes(
        self,
        requests: list[BlueprintChangeRequest],
        write_context: PatchWriteContext,
        progress_callback: PatchProgressCallback | None = None,
    ) -> BlueprintChangeResult:
        """PURPOSE apply multiple approved requests as one patch plan
        DOMAIN  approved blueprint changes
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
        """PURPOSE get the first policy violation for a request list
        DOMAIN  approved blueprint changes
        """
        for request in requests:
            blocked_reason = self._policy.validate_request(request)
            if blocked_reason is not None:
                return blocked_reason
        return None
