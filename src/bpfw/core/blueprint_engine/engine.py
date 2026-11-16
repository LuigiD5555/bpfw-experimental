"""Authority Blueprint Engine for file-change BPFW authority mutations."""

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
    """Apply approved approved file changes to files under ``bpfw/``."""

    def __init__(self, project_root: Path) -> None:
        """Initialize the engine.

        Args:
            project_root: Project root directory.
        """
        self.project_root = project_root
        self._builder = BlueprintPlanBuilder()
        self._policy = BlueprintEngineSafetyPolicy()
        self._patch_engine = AuthorityPatchEngine(project_root=project_root)

    def preview_changes(self, requests: list[BlueprintChangeRequest]) -> BlueprintChangePreview:
        """Preview multiple change requests without writing.

        Args:
            requests: Change requests to preview.

        Returns:
            Structured preview with affected files or blocked reason.
        """
        from bpfw.core.authority.sqlite.migration import active_backend
        if active_backend(self.project_root) == "sqlite":
            from bpfw.core.authority.sqlite.compat import execute_sqlite_plan
            blocked = self._first_blocked_reason(requests)
            if blocked:
                return BlueprintChangePreview(allowed=False, blocked_reason=blocked)
            try:
                plan = self._builder.build_plan(requests)
                changes = execute_sqlite_plan(self.project_root, plan, apply=False)
                return BlueprintChangePreview(allowed=True, operation_count=len(plan.operations),
                                              affected_files=(Path(".bpfw/authority.sqlite"),),
                                              messages=(f"SQLite preview: {changes} logical changes",))
            except Exception as error:
                return BlueprintChangePreview(allowed=False, blocked_reason=str(error))
        blocked_reason = self._first_blocked_reason(requests)
        if blocked_reason is not None:
            return BlueprintChangePreview(allowed=False, blocked_reason=blocked_reason)

        plan = self._builder.build_plan(requests)
        patch_preview = self._patch_engine.preview(plan)
        validation_failed = bool(patch_preview.messages) and not patch_preview.modified_files
        blocked = patch_preview.error_message or ("\n".join(patch_preview.messages) if validation_failed else None)
        return BlueprintChangePreview(
            allowed=blocked is None,
            operation_count=len(plan.operations),
            affected_files=tuple(sorted(plan.affected_files())),
            messages=tuple(patch_preview.messages),
            blocked_reason=blocked,
        )

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
        from bpfw.core.authority.sqlite.migration import active_backend
        if active_backend(self.project_root) == "sqlite":
            from bpfw.core.authority.sqlite.compat import execute_sqlite_plan
            blocked = self._first_blocked_reason(requests)
            if blocked:
                return BlueprintChangeResult(success=False, blocked_reason=blocked)
            if not write_context.is_valid():
                return BlueprintChangeResult(success=False, blocked_reason="Invalid write context")
            try:
                plan = self._builder.build_plan(requests)
                count = execute_sqlite_plan(self.project_root, plan, apply=True)
                return BlueprintChangeResult(success=True, messages=[f"SQLite: {count} changes committed"])
            except Exception as error:
                return BlueprintChangeResult(success=False, blocked_reason=str(error))
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

    def preview_authority_patches(self, edits: list[dict]) -> dict:
        """Preview a logical SQLite change set without committing it."""
        from bpfw.core.authority.sqlite.migration import active_backend
        from bpfw.core.authority.sqlite.store import SqliteAuthorityStore, AuthorityConflict
        if active_backend(self.project_root) != "sqlite":
            raise AuthorityConflict("SQLite authority is not active")
        return SqliteAuthorityStore(self.project_root).apply_patches(edits, dry_run=True)

    def apply_authority_patches(self, edits: list[dict], *, reason: str = "edit") -> dict:
        """Only authorized semantic writer for CSV / table cell patches."""
        from bpfw.core.authority.sqlite.migration import active_backend
        from bpfw.core.authority.sqlite.store import SqliteAuthorityStore, AuthorityConflict
        if active_backend(self.project_root) != "sqlite":
            raise AuthorityConflict("SQLite authority is not active")
        return SqliteAuthorityStore(self.project_root).apply_patches(edits, reason=reason)

    def replace_authority_document(self, document: dict, *, reason: str,
                                   expected_revision: int | None = None) -> int:
        """Compatibility bridge to atomic, incremental document diff persistence."""
        from bpfw.core.authority.sqlite.migration import active_backend
        from bpfw.core.authority.sqlite.store import SqliteAuthorityStore, AuthorityConflict
        if active_backend(self.project_root) != "sqlite":
            raise AuthorityConflict("SQLite authority is not active")
        return SqliteAuthorityStore(self.project_root).replace_document(
            document, actor="blueprint-engine", reason=reason,
            expected_revision=expected_revision)
