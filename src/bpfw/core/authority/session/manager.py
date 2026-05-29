"""Authority session manager for temporary unified interactive persistence."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from bpfw.core.authority import AuthorityError, AuthorityRepository
from bpfw.core.authority.session.recovery import (
    AuthoritySessionMeta,
    read_session_meta,
    utc_now_iso8601,
    write_session_meta,
)
from bpfw.core.authority.session.temporary_blueprint import read_unified_blueprint, write_unified_blueprint
from bpfw.core.catalog.access_control import has_temporary_blueprint_unlock_authorization
from bpfw.core.catalog.drift import compare_declared_to_discovered
from bpfw.core.catalog.models import AUTHORITY_STATE_DEFINED, AUTHORITY_STATE_DRAFT, AUTHORITY_STATE_EMPTY
from bpfw.core.catalog.security import validate_no_blueprint_secrets
from bpfw.core.catalog.validation import validate_blueprint_structure
from bpfw.core.catalog.verify import scan_project_from_blueprint
from bpfw.core.errors import BlueprintLockedError
from bpfw.core.protection.authority import (
    get_authority_protection_status,
    lock_authority,
    unlock_authority,
)


@dataclass(slots=True)
class AuthoritySessionState:
    """In-memory state for one tool authority session."""

    tool_name: str
    project_root: Path
    temporary_path: Path
    meta_path: Path
    blueprint_data: dict[str, Any]


class AuthoritySessionManager:
    """Coordinate pending unified session persistence and one-shot finalization."""

    def __init__(self, project_root: Path, tool_name: str) -> None:
        """Initialize a session manager for one interactive tool.

        Args:
            project_root: Root directory of the target project.
            tool_name: Tool identifier used to name pending session files.
        """

        self.project_root = project_root.resolve()
        self.tool_name = tool_name
        self.pending_dir = self.project_root / "bpfw" / ".pending"
        self.temporary_path = self.pending_dir / f"{tool_name}-session.yaml"
        self.meta_path = self.pending_dir / f"{tool_name}-session.meta.yaml"
        self.state: AuthoritySessionState | None = None

    def begin(
        self,
        *,
        input_func: Callable[[str], str] | None = None,
        print_func: Callable[[str], None] = print,
    ) -> AuthoritySessionState:
        """Start or recover an interactive authority session.

        Args:
            input_func: Optional prompt callback to choose recovery actions.
            print_func: Output callback for user-facing recovery messages.

        Returns:
            Active authority session state with mutable unified blueprint data.
        """

        self._ensure_pending_directory_exists()
        repository = AuthorityRepository(self.project_root)
        authority_document = repository.load()
        persisted_blueprint_data = authority_document.blueprint_data

        existing_meta = read_session_meta(self.meta_path)
        if self.temporary_path.exists() or (existing_meta is not None and existing_meta.status in {"pending", "failed"}):
            action = self._choose_recovery_action(existing_meta=existing_meta, input_func=input_func, print_func=print_func)
            if action == "apply":
                apply_result = self.finalize(print_func=print_func)
                if apply_result != 0:
                    raise RuntimeError("Failed to apply pending authority session.")
                blueprint_data = repository.load().blueprint_data
            elif action == "discard":
                self.discard()
                blueprint_data = persisted_blueprint_data
            else:
                blueprint_data = read_unified_blueprint(self.temporary_path)
        else:
            blueprint_data = persisted_blueprint_data
            write_unified_blueprint(self.temporary_path, blueprint_data)
            current_time = utc_now_iso8601()
            write_session_meta(
                self.meta_path,
                AuthoritySessionMeta(
                    tool_name=self.tool_name,
                    status="pending",
                    created_at=current_time,
                    updated_at=current_time,
                    temporary_path=str(self.temporary_path),
                ),
            )

        self.state = AuthoritySessionState(
            tool_name=self.tool_name,
            project_root=self.project_root,
            temporary_path=self.temporary_path,
            meta_path=self.meta_path,
            blueprint_data=blueprint_data,
        )
        return self.state

    def _ensure_pending_directory_exists(self) -> None:
        """Ensure the tool pending directory exists even when authority is locked.

        This method first attempts a normal directory creation. If that fails with a
        permission error and temporary unlock authorization is active, it temporarily
        unlocks authority resources, creates `bpfw/.pending`, and then re-locks.

        Raises:
            BlueprintLockedError: If pending directory creation requires unlock but
                unlock authorization is missing or unlock/re-lock fails.
            PermissionError: If the directory still cannot be created.
        """

        try:
            self.pending_dir.mkdir(parents=True, exist_ok=True)
            return
        except PermissionError as error:
            if not has_temporary_blueprint_unlock_authorization():
                raise BlueprintLockedError(
                    "Blueprint is locked and pending session directory cannot be created. "
                    "Run in an interactive terminal and approve temporary unlock."
                ) from error

            lock_state = get_authority_protection_status(project_root=self.project_root).status
            if lock_state not in {"locked", "degraded"}:
                raise

            unlock_result = unlock_authority(project_root=self.project_root)
            if unlock_result.status != "unlocked":
                raise BlueprintLockedError(
                    "Blueprint is locked and temporary unlock failed while creating pending session files."
                ) from error

            try:
                self.pending_dir.mkdir(parents=True, exist_ok=True)
            finally:
                relock_result = lock_authority(project_root=self.project_root)
                if relock_result.status not in {"locked", "degraded"}:
                    raise BlueprintLockedError(
                        "Pending session directory was created, but authority re-lock failed."
                    )

    def persist(self) -> None:
        """Persist only the temporary unified blueprint and keep session pending."""

        if self.state is None:
            raise RuntimeError("Authority session has not been started.")

        write_unified_blueprint(self.state.temporary_path, self.state.blueprint_data)
        meta = read_session_meta(self.state.meta_path)
        created_at = meta.created_at if meta is not None else utc_now_iso8601()
        write_session_meta(
            self.state.meta_path,
            AuthoritySessionMeta(
                tool_name=self.tool_name,
                status="pending",
                created_at=created_at,
                updated_at=utc_now_iso8601(),
                temporary_path=str(self.state.temporary_path),
            ),
        )

    def finalize(self, print_func: Callable[[str], None] = print) -> int:
        """Apply pending unified blueprint to protected sharded authority.

        Args:
            print_func: Output callback for failure recovery messaging.

        Returns:
            Exit code where 0 means authority apply succeeded.
        """

        if not self.temporary_path.exists():
            return 0

        meta = read_session_meta(self.meta_path)
        created_at = meta.created_at if meta is not None else utc_now_iso8601()

        try:
            pending_blueprint_data = read_unified_blueprint(self.temporary_path)
            from bpfw.integrations.inspector.base import apply_automatic_authority_fields

            apply_automatic_authority_fields(pending_blueprint_data)
            if self.tool_name == "inspector":
                validation_error = self._validate_pending_blueprint_for_inspector(pending_blueprint_data)
                if validation_error is not None:
                    raise BlueprintLockedError(
                        f"Inspector finalization blocked by verify: {validation_error}"
                    )
            repository = AuthorityRepository(self.project_root)
            authority_document = repository.load()
            authority_document.blueprint_data = pending_blueprint_data
            repository.save(authority_document)
        except (AuthorityError, BlueprintLockedError, OSError, ValueError, ImportError) as error:
            write_session_meta(
                self.meta_path,
                AuthoritySessionMeta(
                    tool_name=self.tool_name,
                    status="failed",
                    created_at=created_at,
                    updated_at=utc_now_iso8601(),
                    temporary_path=str(self.temporary_path),
                    message=str(error),
                ),
            )
            print_func("Failed to apply pending authority session.")
            print_func(f"Pending session preserved: {self.temporary_path}")
            print_func("Recovery options on next run: resume, apply, or discard.")
            return 1

        write_session_meta(
            self.meta_path,
            AuthoritySessionMeta(
                tool_name=self.tool_name,
                status="applied",
                created_at=created_at,
                updated_at=utc_now_iso8601(),
                temporary_path=str(self.temporary_path),
            ),
        )
        self.temporary_path.unlink(missing_ok=True)
        return 0

    def discard(self) -> None:
        """Discard pending unified session files for this tool."""

        self.temporary_path.unlink(missing_ok=True)
        self.meta_path.unlink(missing_ok=True)

    def _choose_recovery_action(
        self,
        *,
        existing_meta: AuthoritySessionMeta | None,
        input_func: Callable[[str], str] | None,
        print_func: Callable[[str], None],
    ) -> str:
        """Resolve recovery action for existing pending or failed session files."""

        if input_func is None:
            return "resume"

        status = existing_meta.status if existing_meta is not None else "pending"
        print_func(f"Existing {self.tool_name} session found ({status}).")
        print_func("Choose: [r]esume pending, [a]pply pending, [d]iscard pending")
        raw_action = input_func("> ").strip().lower()
        if raw_action in {"a", "apply"}:
            return "apply"
        if raw_action in {"d", "discard"}:
            return "discard"
        return "resume"

    def _validate_pending_blueprint_for_inspector(self, blueprint_data: dict[str, Any]) -> str | None:
        """Validate pending inspector blueprint data before sharded final apply.

        Args:
            blueprint_data: Unified pending blueprint dictionary.

        Returns:
            None when validation is allowed; otherwise a blocking message.
        """

        scan_result = scan_project_from_blueprint(
            project_root=self.project_root,
            blueprint_data=blueprint_data,
        )
        blocks = blueprint_data.get("blocks", [])
        if not isinstance(blocks, list) or not blocks:
            authority_state = AUTHORITY_STATE_EMPTY
        else:
            has_incomplete_blocks = any(
                not isinstance(block, dict)
                or not block.get("purpose")
                or not block.get("name")
                or not block.get("domain")
                or not block.get("status")
                for block in blocks
            )
            authority_state = AUTHORITY_STATE_DRAFT if has_incomplete_blocks else AUTHORITY_STATE_DEFINED

        findings = []
        findings.extend(validate_blueprint_structure(blueprint_data=blueprint_data, authority_state=authority_state))
        findings.extend(validate_no_blueprint_secrets(blueprint_data))
        findings.extend(
            compare_declared_to_discovered(
                blueprint_data=blueprint_data,
                discovered_units=scan_result.discovered_units,
                authority_state=authority_state,
            )
        )
        blocking = [finding for finding in findings if finding.severity == "block"]
        if blocking:
            return blocking[0].message
        return None
