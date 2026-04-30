"""Command registry for BPFW engine pipelines — MVP Catalog Mode."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json

from bpfw.access.authorization_policy import AccessAuthorizationError
from bpfw.access.grant_store import AccessGrantStore
from bpfw.access.service import AccessService
from bpfw.authority.lock_manager import AuthorityLockManager
from bpfw.authority.lock_policy import OsLockPolicyError
from bpfw.authority.policy import AuthorityPolicy
from bpfw.authority.resources import AuthorityResourceRegistry
from bpfw.authority.state import (
    AuthorityState,
    UnlockWindow,
    clear_unlock_window,
    load_authority_state,
    save_authority_state,
    set_unlock_window,
    _window_from_dict,
)
from bpfw.blueprint.snapshot import build_snapshot
from bpfw.blueprint.validator import validate_blueprint
from bpfw.core.pipeline import Pipeline, PipelineStep
from bpfw.core.result import ResultStatus, StepResult
from bpfw.enforcement.pre_commit import HookInstallError, install_pre_commit_hook
from bpfw.integrity.manifest import IntegrityManifestError, write_manifest
from bpfw.init.acceptor import InitialBaselineAcceptor
from bpfw.init.detector import ProjectDetector
from bpfw.init.generator import InitialBlueprintGenerator
from bpfw.init.scanner import MechanicalProjectScanner
from bpfw.integrity.signer import IntegritySigningError
from bpfw.integrity.verifier import verify_integrity
from bpfw.security.keyring import ensure_local_hmac_key


@dataclass(slots=True)
class StaticStep(PipelineStep):
    """MVP placeholder step used for wizard (not implemented yet)."""

    name: str
    message: str

    def run(self, context) -> StepResult:  # noqa: ANN001
        del context
        return StepResult(
            status=ResultStatus.WARNING,
            message=self.message,
            source=self.name,
            details={"implementation_state": "not_implemented"},
            suggested_actions=["Wizard will be implemented in future prompts"],
        )


def _parse_ttl_to_minutes(raw_ttl: str) -> int:
    """Parse TTL string to minutes for unlock duration."""
    normalized = raw_ttl.strip().lower()
    if not normalized:
        raise ValueError("Missing --ttl value")
    if normalized.endswith("m"):
        return int(normalized[:-1] or "0")
    if normalized.endswith("h"):
        return int(normalized[:-1] or "0") * 60
    return int(normalized)


def _normalize_resource_id(resource_id: str) -> str:
    """Normalize resource ID shorthand to full ID."""
    normalized = resource_id.strip()
    if normalized == "blueprint":
        return "project_blueprint"
    if normalized == "architecture":
        return "architecture_profile"
    return normalized


def _build_unsealed_block_message() -> str:
    """Build error message for unsealed projects."""
    return "Project is not sealed.\nRun bpfw init or accept the generated baseline."


def _ensure_manifest_for_protected_mode(project_root):  # noqa: ANN001
    """Ensure manifest exists when protection is enabled."""
    state = load_authority_state(project_root=project_root)
    manifest_file = project_root / ".bpfw/manifest.json"
    if state.protection_enabled and not manifest_file.exists():
        raise RuntimeError(_build_unsealed_block_message())


@dataclass(slots=True)
class VerifyAuthorityStep(PipelineStep):
    """Verify authority resources haven't been manually edited."""

    name: str = "authority.verify"

    def _blocked_message(self, relative_path: str) -> str:
        return (
            "CRITICAL\n\n"
            "Authority drift detected.\n\n"
            "Resource:\n"
            f"{relative_path}\n\n"
            "Direct authority edits are not allowed.\n\n"
            "Do not retry this edit.\n\n"
            "Allowed next action:\n"
            "Revert the manual edit and use unlock flow."
        )

    def run(self, context) -> StepResult:  # noqa: ANN001
        from bpfw.authority.resources import AuthorityResourceRegistry
        from bpfw.integrity.manifest import IntegrityManifestError, load_manifest, manifest_path
        from bpfw.integrity.hash_provider import compute_sha256

        try:
            manifest_payload = load_manifest(project_root=context.project_root)
        except IntegrityManifestError:
            return StepResult(
                status=ResultStatus.BLOCK,
                message="Project is not sealed.\nRun bpfw init or accept the generated baseline.",
                source=self.name,
            )

        files = manifest_payload.get("files")
        if not isinstance(files, list):
            return StepResult(status=ResultStatus.OK, message="Authority verify skipped because manifest format is invalid", source=self.name)

        registry = AuthorityResourceRegistry()
        changed_resources: dict[str, str] = {}

        for entry in files:
            if not isinstance(entry, dict):
                continue
            relative_path = str(entry.get("path", "")).strip()
            expected_hash = str(entry.get("sha256", "")).strip()
            if not relative_path or not expected_hash:
                continue

            absolute_path = context.project_root / relative_path
            if not absolute_path.exists() or not absolute_path.is_file():
                continue
            if compute_sha256(absolute_path) == expected_hash:
                continue
            if registry.is_authority_path(relative_path):
                resource = registry.resolve_by_path(relative_path)
                changed_resources[relative_path] = resource.resource_id if resource is not None else relative_path

        if not changed_resources:
            return StepResult(
                status=ResultStatus.OK,
                message="Authority resources validated successfully",
                source=self.name,
                details={"authority_manifest_path": str(manifest_path(project_root=context.project_root))},
            )
        relative_path, resource_id = sorted(changed_resources.items())[0]
        return StepResult(
            status=ResultStatus.CRITICAL,
            message=self._blocked_message(relative_path=relative_path),
            source=self.name,
            details={"error_code": "AUTH001", "resource_id": resource_id},
            affected_resources=[str(context.project_root / relative_path)],
            suggested_actions=["Revert manual authority edits and use unlock flow."],
        )


@dataclass(slots=True)
class AuthoritySealPrecheckStep(PipelineStep):
    """Prevent sealing unauthorized authority drift into the manifest."""

    name: str = "authority.seal_precheck"

    def run(self, context) -> StepResult:  # noqa: ANN001
        from bpfw.access.grant_store import AccessGrantStore
        from bpfw.authority.resources import AuthorityResourceRegistry
        from bpfw.integrity.hash_provider import compute_sha256
        from bpfw.integrity.manifest import IntegrityManifestError, load_manifest

        manifest_file = context.project_root / ".bpfw/manifest.json"
        if not manifest_file.exists():
            if str(context.command_arguments.get("init_accept_scan", "")).strip().lower() == "true":
                return StepResult(status=ResultStatus.OK, message="Initial baseline seal precheck passed", source=self.name)
            return StepResult(
                status=ResultStatus.BLOCK,
                message="Cannot seal authority drift.\n\nProject is not sealed yet.\nUse `bpfw init` to create the first baseline.",
                source=self.name,
                suggested_actions=["Run `bpfw init` and accept the initial baseline before writing a manifest."],
            )

        try:
            manifest_payload = load_manifest(project_root=context.project_root)
        except IntegrityManifestError as error:
            return StepResult(status=ResultStatus.BLOCK, message=str(error), source=self.name)

        files = manifest_payload.get("files")
        if not isinstance(files, list):
            return StepResult(status=ResultStatus.BLOCK, message="Cannot seal authority drift.\n\nManifest format is invalid.", source=self.name)

        registry = AuthorityResourceRegistry()
        drifted_authority_paths: dict[str, str] = {}
        for entry in files:
            if not isinstance(entry, dict):
                continue
            relative_path = str(entry.get("path", "")).strip()
            expected_hash = str(entry.get("sha256", "")).strip()
            if not relative_path or not expected_hash:
                continue
            absolute_path = context.project_root / relative_path
            if not absolute_path.exists() or not absolute_path.is_file():
                continue
            if compute_sha256(absolute_path) == expected_hash:
                continue
            if registry.is_authority_path(relative_path):
                resource = registry.resolve_by_path(relative_path)
                drifted_authority_paths[relative_path] = resource.resource_id if resource is not None else relative_path

        if not drifted_authority_paths:
            return StepResult(status=ResultStatus.OK, message="Authority seal precheck passed", source=self.name)

        audit_path = context.project_root / ".bpfw/audit/authority-events.jsonl"
        audit_events: list[dict[str, str]] = []
        if audit_path.exists():
            for raw_line in audit_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    audit_events.append({str(key): str(value) for key, value in payload.items()})

        active_grants = {grant.grant_id: grant for grant in AccessGrantStore().list_active(project_root=context.project_root)}

        for relative_path, resource_id in sorted(drifted_authority_paths.items()):
            matching_event = next(
                (
                    event
                    for event in reversed(audit_events)
                    if event.get("event_type") == "authority_change_applied" and event.get("resource_id") == resource_id
                ),
                None,
            )
            if matching_event is None:
                return StepResult(
                    status=ResultStatus.BLOCK,
                    message=(
                        "Cannot seal authority drift.\n\n"
                        "The following authority resource changed outside controlled authority operation:\n"
                        f"- {relative_path}\n\n"
                        "Use unlock flow."
                    ),
                    source=self.name,
                    affected_resources=[str(context.project_root / relative_path)],
                )
            grant_id = matching_event.get("grant_id", "")
            if not grant_id or grant_id not in active_grants:
                return StepResult(
                    status=ResultStatus.BLOCK,
                    message=(
                        "Cannot seal authority drift.\n\n"
                        "The following authority resource changed with invalid authority grant:\n"
                        f"- {relative_path}\n\n"
                        "Use unlock flow."
                    ),
                    source=self.name,
                    affected_resources=[str(context.project_root / relative_path)],
                )
            matched_grant = active_grants[grant_id]
            if matched_grant.resource_id != resource_id:
                return StepResult(
                    status=ResultStatus.BLOCK,
                    message=(
                        "Cannot seal authority drift.\n\n"
                        "The following authority resource changed with invalid authority grant:\n"
                        f"- {relative_path}\n\n"
                        "Use unlock flow."
                    ),
                    source=self.name,
                    affected_resources=[str(context.project_root / relative_path)],
                )

        return StepResult(status=ResultStatus.OK, message="Authority seal precheck passed", source=self.name)


@dataclass(slots=True)
class VerifyBlueprintStep(PipelineStep):
    """Verify blueprint.yaml exists and is valid."""

    name: str = "blueprint.verify"

    def run(self, context) -> StepResult:  # noqa: ANN001
        validation_result = validate_blueprint(project_root=context.project_root)
        if validation_result.is_valid and validation_result.blueprint is not None:
            snapshot = build_snapshot(validation_result.blueprint)
            return StepResult(
                status=ResultStatus.OK,
                message="Blueprint loaded and validated successfully",
                source=self.name,
                details={
                    "responsibility_count": str(snapshot.responsibility_count),
                    "blueprint_path": snapshot.blueprint_path,
                },
            )

        first_error = validation_result.errors[0]
        return StepResult(
            status=ResultStatus.BLOCK,
            message=first_error.message,
            source=self.name,
            details={"error_code": first_error.code},
            affected_resources=[first_error.file_path],
            suggested_actions=[first_error.recommendation],
        )


@dataclass(slots=True)
class ManifestWriteStep(PipelineStep):
    """Generate integrity manifest from current approved state."""

    name: str = "integrity.manifest.write"

    def run(self, context) -> StepResult:  # noqa: ANN001
        try:
            write_result = write_manifest(project_root=context.project_root)
        except (IntegrityManifestError, IntegritySigningError) as error:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=str(error),
                source=self.name,
                details={
                    "error_code": "INT_WRITE_BLOCK",
                    "manifest_path": str(context.project_root / ".bpfw/manifest.json"),
                },
                affected_resources=[str(context.project_root / ".bpfw/manifest.json")],
                suggested_actions=["Configure BPFW_MANIFEST_HMAC_KEY and run `bpfw init` again"],
            )

        return StepResult(
            status=ResultStatus.OK,
            message="Integrity manifest generated and signed successfully",
            source=self.name,
            details={
                "manifest_path": str(write_result.manifest_path),
                "manifest_updated_at": write_result.updated_at,
                "integrity_checked_files": str(write_result.file_count),
            },
        )


@dataclass(slots=True)
class VerifyIntegrityStep(PipelineStep):
    """Verify integrity manifest signature and protected file hashes."""

    strict: bool = True
    name: str = "integrity.verify"

    def run(self, context) -> StepResult:  # noqa: ANN001
        ci_mode_enabled = str(context.command_arguments.get("ci", "")).strip().lower() == "true"
        diagnostic_mode_enabled = str(context.command_arguments.get("diagnostic", "")).strip().lower() == "true"
        strict_mode_enabled = self.strict and not diagnostic_mode_enabled
        verification_result = verify_integrity(project_root=context.project_root)
        if verification_result.issues:
            first_issue = verification_result.issues[0]

            status = ResultStatus.WARNING
            if first_issue.severity == "critical":
                status = ResultStatus.CRITICAL
            elif first_issue.severity == "block":
                status = ResultStatus.BLOCK

            if any(issue.severity == "critical" for issue in verification_result.issues):
                status = ResultStatus.CRITICAL
            elif any(issue.severity == "block" for issue in verification_result.issues):
                status = ResultStatus.BLOCK

            if not strict_mode_enabled and verification_result.only_precondition_issues and not ci_mode_enabled:
                status = ResultStatus.WARNING

            protected_precondition_issue_codes = {"INT001", "INT002", "AUTH001", "INT004"}
            protected_precondition_issue_found = any(
                issue.code in protected_precondition_issue_codes for issue in verification_result.issues
            )
            if ci_mode_enabled and (
                verification_result.checked_files == 0 or protected_precondition_issue_found
            ):
                status = ResultStatus.CRITICAL
                return StepResult(
                    status=status,
                    message=(
                        "Protected integrity could not be verified, commit blocked.\n\n"
                        f"{first_issue.message}"
                    ),
                    source=self.name,
                    details={
                        "error_code": first_issue.code,
                        "manifest_path": verification_result.manifest_path,
                        "integrity_checked_files": str(verification_result.checked_files),
                    },
                    affected_resources=[first_issue.file_path] if first_issue.file_path else [],
                    suggested_actions=[first_issue.recommendation],
                )

            return StepResult(
                status=status,
                message=first_issue.message,
                source=self.name,
                details={
                    "error_code": first_issue.code,
                    "manifest_path": verification_result.manifest_path,
                    "integrity_checked_files": str(verification_result.checked_files),
                },
                affected_resources=[first_issue.file_path] if first_issue.file_path else [],
                suggested_actions=[first_issue.recommendation],
            )

        return StepResult(
            status=ResultStatus.CRITICAL,
            message="Protected integrity could not be verified, commit blocked.\n\nChecked files: 0",
            source=self.name,
            details={
                "error_code": "INT008",
                "manifest_path": verification_result.manifest_path,
                "integrity_checked_files": str(verification_result.checked_files),
            },
            suggested_actions=["Regenerate manifest from trusted state and ensure protected targets are included"],
        ) if ci_mode_enabled and verification_result.checked_files == 0 else StepResult(
            status=ResultStatus.OK,
            message="Integrity verification passed",
            source=self.name,
            details={
                "manifest_path": verification_result.manifest_path,
                "integrity_checked_files": str(verification_result.checked_files),
            },
        )


@dataclass(slots=True)
class InstallHooksStep(PipelineStep):
    """Install deterministic git hooks for local enforcement."""

    name: str = "enforcement.install_hooks"

    def run(self, context) -> StepResult:  # noqa: ANN001
        try:
            installed_hook = install_pre_commit_hook(project_root=context.project_root)
        except HookInstallError as error:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=str(error),
                source=self.name,
                details={"error_code": "ENF_HOOK_INSTALL_BLOCK"},
                suggested_actions=["Run inside a git repository with a writable .git/hooks directory"],
            )

        return StepResult(
            status=ResultStatus.OK,
            message="Pre-commit hook installed successfully",
            source=self.name,
            details={"installed_hook_path": str(installed_hook)},
            affected_resources=[str(installed_hook)],
        )


@dataclass(slots=True)
class AuthorityStatusStep(PipelineStep):
    """Report authority lock and protection status."""

    name: str = "authority.status"

    def run(self, context) -> StepResult:  # noqa: ANN001
        state = load_authority_state(project_root=context.project_root)
        registry = AuthorityResourceRegistry()
        resources = registry.list_resources()
        manifest_path = context.project_root / ".bpfw/manifest.json"
        hooks_path = context.project_root / ".git" / "hooks" / "pre-commit"

        # Check if resources are locked based on unlock window
        unlocked_resource_id = state.active_unlock_window.resource_id if state.active_unlock_window else None
        locked_count = sum(1 for r in resources if r.resource_id != unlocked_resource_id)
        total_count = len(resources)

        status_lines = [
            f"Protection enabled: {state.protection_enabled}",
            f"Locked resources: {locked_count} / {total_count}",
            f"Manifest sealed: {manifest_path.exists()}",
            f"Git hooks installed: {hooks_path.exists()}",
        ]

        if state.active_unlock_window:
            status_lines.append(f"Unlock window active: YES (expires at {state.active_unlock_window.expires_at})")
        else:
            status_lines.append("Unlock window active: NO")

        if resources:
            status_lines.append("\nResources:")
            for resource in resources:
                is_unlocked = resource.resource_id == unlocked_resource_id
                lock_status = "UNLOCKED" if is_unlocked else "LOCKED"
                status_lines.append(f"  - {resource.resource_id}: {lock_status}")

        return StepResult(
            status=ResultStatus.OK,
            message="Authority status reported",
            source=self.name,
            details={
                "protection_enabled": str(state.protection_enabled).lower(),
                "locked_resource_count": str(locked_count),
                "total_resource_count": str(total_count),
                "manifest_sealed": str(manifest_path.exists()).lower(),
                "git_hooks_installed": str(hooks_path.exists()).lower(),
                "unlock_window_active": str(state.active_unlock_window is not None).lower(),
            },
        )


@dataclass(slots=True)
class AuthorityLockStep(PipelineStep):
    """Lock all authority resources against edits."""

    name: str = "authority.lock"

    def run(self, context) -> StepResult:  # noqa: ANN001
        try:
            _ensure_manifest_for_protected_mode(project_root=context.project_root)
        except RuntimeError as error:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=str(error),
                source=self.name,
                details={"error_code": "AUTH_LOCK_PRECHECK"},
            )

        lock_manager = AuthorityLockManager()
        state = load_authority_state(project_root=context.project_root)

        try:
            lock_manager.lock_all(project_root=context.project_root)
        except OsLockPolicyError as error:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=str(error),
                source=self.name,
                details={"error_code": "AUTH_LOCK_OS_BLOCK"},
            )

        clear_unlock_window(project_root=context.project_root, state=state)
        save_authority_state(project_root=context.project_root, state=state)

        registry = AuthorityResourceRegistry()
        locked_count = len(registry.list_resources())

        return StepResult(
            status=ResultStatus.OK,
            message=f"Locked {locked_count} authority resource(s)",
            source=self.name,
            details={"locked_resource_count": str(locked_count)},
        )


@dataclass(slots=True)
class AuthorityUnlockStep(PipelineStep):
    """Unlock a specific authority resource with TTL."""

    name: str = "authority.unlock"

    def run(self, context) -> StepResult:  # noqa: ANN001
        resource_id_input = context.command_arguments.get("resource_id", "").strip()
        if not resource_id_input:
            return StepResult(
                status=ResultStatus.BLOCK,
                message="Missing resource_id. Usage: bpfw unlock <resource>",
                source=self.name,
                details={"error_code": "AUTH_UNLOCK_USAGE"},
            )

        resource_id = _normalize_resource_id(resource_id_input)
        try:
            _ensure_manifest_for_protected_mode(project_root=context.project_root)
        except RuntimeError as error:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=str(error),
                source=self.name,
                details={"error_code": "AUTH_UNLOCK_PRECHECK"},
            )

        registry = AuthorityResourceRegistry()
        resource = registry.get(resource_id)
        if resource is None:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=f"Resource not found: {resource_id}",
                source=self.name,
                details={"error_code": "AUTH_UNLOCK_NOT_FOUND", "resource_id": resource_id},
                suggested_actions=["Use 'bpfw status' to list available resources"],
            )

        ttl_minutes = _parse_ttl_to_minutes(context.command_arguments.get("ttl", "10m"))
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        unlock_window = UnlockWindow(
            resource_id=resource_id,
            resource_path=resource.path if resource else "",
            scope="manual",
            operation="unlock",
            expires_at=expires_at.astimezone(timezone.utc).isoformat(),
            granted_by="cli",
            request_id="",
            grant_id=f"manual_{resource_id}_{int(expires_at.timestamp())}",
        )

        state = load_authority_state(project_root=context.project_root)
        state.active_unlock_window = unlock_window
        save_authority_state(project_root=context.project_root, state=state)

        # MVP: Skip OS-level unlock (not required for catalog mode, and may fail on some filesystems)

        return StepResult(
            status=ResultStatus.OK,
            message=f"Unlocked resource '{resource_id}' for {ttl_minutes} minutes",
            source=self.name,
            details={
                "resource_id": resource_id,
                "expires_at": expires_at.astimezone(timezone.utc).isoformat(),
                "ttl_minutes": str(ttl_minutes),
            },
        )


@dataclass(slots=True)
class InitProjectStep(PipelineStep):
    """Initialize project with baseline blueprint and manifest."""

    name: str = "init.project"

    def run(self, context) -> StepResult:  # noqa: ANN001
        force_new = str(context.command_arguments.get("force_new", "")).strip().lower() == "true"
        accept_scan = str(context.command_arguments.get("accept_scan", "")).strip().lower() == "true"
        watch_mode = str(context.command_arguments.get("watch", "")).strip().lower() == "true"
        no_os_lock = str(context.command_arguments.get("no_os_lock", "")).strip().lower() == "true"

        detector = ProjectDetector()
        detection_result = detector.detect(project_root=context.project_root)

        if detection_result.is_initialized and not force_new:
            return StepResult(
                status=ResultStatus.WARNING,
                message="Project already initialized.\nUse --force-new to reinitialize.",
                source=self.name,
                details={"existing_blueprint": str(detection_result.project_root / "blueprint.yaml")},
            )

        ensure_local_hmac_key()
        scanner = MechanicalProjectScanner(project_root=context.project_root)
        scan_result = scanner.scan()

        generator = InitialBlueprintGenerator(scan_result=scan_result)
        entries = generator.generate()

        acceptor = InitialBaselineAcceptor(project_root=context.project_root, entries=entries, accept=accept_scan)

        try:
            acceptor.accept()
        except RuntimeError as error:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=str(error),
                source=self.name,
                details={"error_code": "INIT_ACCEPT_BLOCK"},
            )

        if accept_scan:
            try:
                write_manifest(project_root=context.project_root)
            except (IntegrityManifestError, IntegritySigningError) as error:
                return StepResult(
                    status=ResultStatus.BLOCK,
                    message=f"Blueprint generated but manifest failed: {error}",
                    source=self.name,
                    details={"error_code": "INIT_MANIFEST_BLOCK"},
                )

        try:
            install_pre_commit_hook(project_root=context.project_root)
        except HookInstallError:
            pass

        state = load_authority_state(project_root=context.project_root)
        state.protection_enabled = True
        save_authority_state(project_root=context.project_root, state=state)

        if not no_os_lock:
            lock_manager = AuthorityLockManager()
            try:
                lock_manager.lock_all(project_root=context.project_root)
            except OsLockPolicyError:
                pass

        return StepResult(
            status=ResultStatus.OK,
            message="Project initialized successfully",
            source=self.name,
            details={
                "blueprint_generated": str(acceptor.blueprint_path),
                "manifest_sealed": str(accept_scan).lower(),
                "protection_enabled": "true",
            },
            affected_resources=[str(acceptor.blueprint_path)],
        )


def build_default_registry() -> dict[str, Pipeline]:
    """Build default pipeline registry for BPFW MVP."""

    verify_pipeline = Pipeline(
        name="verify",
        steps=[
            VerifyBlueprintStep(),
            VerifyAuthorityStep(),
            VerifyIntegrityStep(strict=True),
        ],
    )

    lock_pipeline = Pipeline(
        name="lock",
        steps=[AuthorityLockStep()],
    )

    unlock_pipeline = Pipeline(
        name="unlock",
        steps=[AuthorityUnlockStep()],
    )

    status_pipeline = Pipeline(
        name="status",
        steps=[AuthorityStatusStep()],
    )

    init_pipeline = Pipeline(
        name="init",
        steps=[InitProjectStep()],
    )

    wizard_pipeline = Pipeline(
        name="wizard",
        steps=[
            StaticStep(
                name="wizard.scaffold",
                message="Wizard not implemented yet. TODO: implement interactive blueprint scaffolding in future prompts.",
            ),
        ],
    )

    return {
        "verify": verify_pipeline,
        "lock": lock_pipeline,
        "unlock": unlock_pipeline,
        "status": status_pipeline,
        "init": init_pipeline,
        "wizard": wizard_pipeline,
    }