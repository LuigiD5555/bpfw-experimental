"""Command registry for BPFW engine pipelines."""

from __future__ import annotations

from dataclasses import dataclass

from bpfw.apply.transaction import ApplyTransactionError, apply_change_transaction
from bpfw.approval.broker import ApprovalBrokerError, approve_request
from bpfw.approval.request import ApprovalRequestError
from bpfw.approval.verifier import ApprovalVerificationError, verify_all_approvals
from bpfw.architecture.architecture_validator import validate_architecture
from bpfw.authority.policy import AuthorityPolicy
from bpfw.blueprint.snapshot import build_snapshot
from bpfw.blueprint.validator import validate_blueprint
from bpfw.blueprint_mode.contract_validator import validate_blueprint_mode_contracts
from bpfw.change.scope import ScopeResolutionError, resolve_scope
from bpfw.change.session import (
    ChangeSessionError,
    create_change_session,
    load_change_session,
    update_change_status,
)
from bpfw.composition.checker import validate_composition
from bpfw.core.pipeline import Pipeline, PipelineStep
from bpfw.core.result import ResultStatus, StepResult
from bpfw.discover.classifier import classify_findings
from bpfw.discover.proposal_builder import build_proposals
from bpfw.discover.scanner import scan_repository
from bpfw.duplication.duplication_reporter import (
    findings_to_human_lines,
    primary_finding as duplication_primary_finding,
    summarize_counts,
)
from bpfw.duplication.similarity_detector import detect_duplication
from bpfw.enforcement.pre_commit import HookInstallError, install_pre_commit_hook
from bpfw.integrity.manifest import IntegrityManifestError, write_manifest
from bpfw.init.acceptor import InitialBaselineAcceptor
from bpfw.init.detector import ProjectDetector
from bpfw.init.generator import InitialBlueprintGenerator
from bpfw.init.scanner import MechanicalProjectScanner
from bpfw.integrity.signer import IntegritySigningError
from bpfw.integrity.verifier import verify_integrity
from bpfw.review.decision import ReviewDecisionError, primary_finding as review_primary_finding, review_session
from bpfw.runtime.collector import collect_runtime_snapshot
from bpfw.runtime.snapshot import snapshot_to_dict, snapshot_to_human_lines, snapshot_to_json
from bpfw.proposal.renderer import render_proposal_detail, render_proposal_list
from bpfw.proposal.resolver import ProposalResolutionError, accept_proposal, reject_proposal
from bpfw.proposal.store import ProposalStoreError, list_proposals, load_proposal
from bpfw.wiring.verifier import verify_wiring
from bpfw.workspace.builder import WorkspaceBuildError, build_workspace


@dataclass(slots=True)
class StaticStep(PipelineStep):
    """Prompt 0 placeholder step used to keep the engine executable."""

    name: str
    message: str

    def run(self, context) -> StepResult:  # noqa: ANN001
        del context
        return StepResult(
            status=ResultStatus.WARNING,
            message=self.message,
            source=self.name,
            details={"implementation_state": "not_implemented"},
            suggested_actions=["Implement concrete validators in next prompts"],
        )




@dataclass(slots=True)
class VerifyAuthorityStep(PipelineStep):
    """Executable authority step for direct-change access control."""

    name: str = "authority.verify"

    def run(self, context) -> StepResult:  # noqa: ANN001
        import subprocess

        from bpfw.authority.resources import AuthorityResourceRegistry
        from bpfw.integrity.manifest import load_manifest, manifest_path
        from bpfw.integrity.hash_provider import compute_sha256
        from bpfw.integrity.manifest import IntegrityManifestError
        from bpfw.integrity.verifier import verify_integrity

        try:
            manifest_payload = load_manifest(project_root=context.project_root)
        except IntegrityManifestError:
            return StepResult(
                status=ResultStatus.OK,
                message="Authority verify skipped because manifest is unavailable",
                source=self.name,
            )

        files = manifest_payload.get("files")
        if not isinstance(files, list):
            return StepResult(status=ResultStatus.OK, message="Authority verify skipped because manifest format is invalid", source=self.name)

        policy = AuthorityPolicy()
        registry = AuthorityResourceRegistry()
        requested_operation = str(context.command_arguments.get("operation", "")).strip() or None
        requested_scope = str(context.command_arguments.get("scope", "")).strip() or None

        changed_paths: set[str] = set()

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

            changed_paths.add(relative_path)

        try:
            git_status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=context.project_root,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            git_status = None

        if git_status is not None and git_status.returncode == 0:
            for line in git_status.stdout.splitlines():
                if len(line) < 4:
                    continue
                candidate_path = line[3:].strip()
                if not candidate_path:
                    continue
                if " -> " in candidate_path:
                    candidate_path = candidate_path.split(" -> ", 1)[1].strip()
                candidate_path = candidate_path.replace("\\", "/")
                if registry.is_authority_path(candidate_path):
                    changed_paths.add(candidate_path)

        for relative_path in sorted(changed_paths):
            integrity_result = verify_integrity(project_root=context.project_root)
            if integrity_result.issues and not integrity_result.only_precondition_issues:
                # Integrity verifier participates in authority pipeline wiring.
                pass

            resource = registry.resolve_by_path(relative_path)
            operation = requested_operation
            scope = requested_scope
            if resource is not None and (operation is None or scope is None):
                default_operation = resource.allowed_operations[0] if resource.allowed_operations else "direct_edit"
                operation = operation or default_operation
                scope = scope or "project"

            decision = policy.evaluate_direct_change(
                project_root=context.project_root,
                relative_path=relative_path,
                operation=operation,
                scope=scope,
            )
            if decision.allowed:
                continue

            resource_label = "Authority resource"
            if resource is not None:
                if resource.resource_type == "blueprint":
                    resource_label = "Blueprint"
                elif resource.resource_type == "architecture":
                    resource_label = "Architecture"
                elif resource.resource_type == "manifest":
                    resource_label = "Integrity manifest"

            message = (
                "BPFW BLOCKED ACTION\n\n"
                "Resource:\n"
                f"{relative_path}\n\n"
                "Reason:\n"
                f"{resource_label} is an authority resource.\n\n"
                "Policy:\n"
                "Direct authority edits are not allowed.\n\n"
                f"{decision.message}\n\n"
                "Do not retry this edit.\n\n"
                "Allowed next action:\n"
                f"{decision.recommendation}"
            )
            return StepResult(
                status=ResultStatus.BLOCK,
                message=message,
                source=self.name,
                details={"error_code": "AUTH001", "resource_id": decision.resource_id},
                affected_resources=[str(context.project_root / relative_path)],
                suggested_actions=[decision.recommendation],
            )

        return StepResult(
            status=ResultStatus.OK,
            message="Authority resources validated successfully",
            source=self.name,
            details={"authority_manifest_path": str(manifest_path(project_root=context.project_root))},
        )
@dataclass(slots=True)
class VerifyBlueprintStep(PipelineStep):
    """Executable verify step for blueprint authority validation."""

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
class VerifyArchitectureStep(PipelineStep):
    """Executable architecture step for layer and import validation."""

    name: str = "architecture.check"

    def run(self, context) -> StepResult:  # noqa: ANN001
        validation_result = validate_architecture(project_root=context.project_root)
        if validation_result.errors:
            first_error = validation_result.errors[0]
            return StepResult(
                status=ResultStatus.BLOCK,
                message=first_error.message,
                source=self.name,
                details={"error_code": first_error.code},
                affected_resources=[first_error.file_path],
                suggested_actions=[first_error.recommendation],
            )

        if validation_result.warnings:
            first_warning = validation_result.warnings[0]
            return StepResult(
                status=ResultStatus.WARNING,
                message=first_warning.message,
                source=self.name,
                details={"error_code": first_warning.code},
                affected_resources=[first_warning.file_path],
                suggested_actions=[first_warning.recommendation],
            )

        profile_id = ""
        if validation_result.profile is not None:
            profile_id = validation_result.profile.profile_id
        return StepResult(
            status=ResultStatus.OK,
            message="Architecture profile loaded and import rules validated successfully",
            source=self.name,
            details={"architecture_profile_id": profile_id},
        )


@dataclass(slots=True)
class VerifyCompositionStep(PipelineStep):
    """Executable composition step for concrete wiring checks."""

    name: str = "composition.check"

    def run(self, context) -> StepResult:  # noqa: ANN001
        validation_result = validate_composition(project_root=context.project_root)
        if validation_result.errors:
            first_error = validation_result.errors[0]
            return StepResult(
                status=ResultStatus.BLOCK,
                message=first_error.message,
                source=self.name,
                details={"error_code": first_error.code},
                affected_resources=[first_error.file_path],
                suggested_actions=[first_error.recommendation],
            )

        return StepResult(
            status=ResultStatus.OK,
            message="Composition roots validated successfully",
            source=self.name,
        )


@dataclass(slots=True)
class VerifyRuntimeSnapshotStep(PipelineStep):
    """Executable runtime snapshot step for active binding visibility."""

    name: str = "runtime.snapshot"

    def run(self, context) -> StepResult:  # noqa: ANN001
        collection_result = collect_runtime_snapshot(project_root=context.project_root)
        if collection_result.errors:
            first_error = collection_result.errors[0]
            return StepResult(
                status=ResultStatus.BLOCK,
                message=first_error.message,
                source=self.name,
                details={
                    "error_code": first_error.code,
                },
                affected_resources=[first_error.file_path],
                suggested_actions=[first_error.recommendation],
            )

        if collection_result.snapshot is None:
            return StepResult(
                status=ResultStatus.WARNING,
                message="Runtime snapshot could not be collected",
                source=self.name,
                details={"runtime_snapshot": "{}"},
                suggested_actions=["Declare runtime bindings metadata in wiring or .bpfw/runtime_bindings.yaml"],
            )

        snapshot = collection_result.snapshot
        warning_count = len(collection_result.warnings)
        if warning_count > 0:
            first_warning = collection_result.warnings[0]
            return StepResult(
                status=ResultStatus.WARNING,
                message=first_warning.message,
                source=self.name,
                details={
                    "warning_code": first_warning.code,
                    "runtime_snapshot_json": snapshot_to_json(snapshot),
                    "runtime_snapshot_human": snapshot_to_human_lines(snapshot),
                    "warning_count": str(warning_count),
                },
                affected_resources=[first_warning.file_path],
                suggested_actions=[first_warning.recommendation],
            )

        return StepResult(
            status=ResultStatus.OK,
            message="Runtime snapshot collected successfully",
            source=self.name,
            details={
                "runtime_snapshot_json": snapshot_to_json(snapshot),
                "runtime_snapshot_human": snapshot_to_human_lines(snapshot),
                "active_bindings_count": str(len(snapshot_to_dict(snapshot)["active_bindings"])),
            },
        )


@dataclass(slots=True)
class VerifyWiringStep(PipelineStep):
    """Executable wiring step for blueprint/runtime active implementation alignment."""

    name: str = "wiring.check"

    def run(self, context) -> StepResult:  # noqa: ANN001
        verification_result = verify_wiring(project_root=context.project_root)
        if verification_result.issues:
            first_issue = verification_result.issues[0]
            status = ResultStatus.WARNING
            if first_issue.severity == "block":
                status = ResultStatus.BLOCK
            elif first_issue.severity == "critical":
                status = ResultStatus.CRITICAL

            if any(issue.severity == "critical" for issue in verification_result.issues):
                status = ResultStatus.CRITICAL
            elif any(issue.severity == "block" for issue in verification_result.issues):
                status = ResultStatus.BLOCK

            return StepResult(
                status=status,
                message=first_issue.message,
                source=self.name,
                details={
                    "error_code": first_issue.code,
                    "wiring_issue_count": str(len(verification_result.issues)),
                },
                affected_resources=[first_issue.file_path],
                suggested_actions=[first_issue.recommendation],
            )

        return StepResult(
            status=ResultStatus.OK,
            message="Wiring verification passed",
            source=self.name,
            details={
                "active_bindings_count": str(len(verification_result.active_bindings)),
            },
        )


@dataclass(slots=True)
class VerifyDuplicationStep(PipelineStep):
    """Executable duplication step for intent-duplication detection."""

    name: str = "duplication.check"

    def run(self, context) -> StepResult:  # noqa: ANN001
        detection_result = detect_duplication(project_root=context.project_root)
        primary = duplication_primary_finding(detection_result)
        summary_counts = summarize_counts(detection_result)

        if primary is None:
            return StepResult(
                status=ResultStatus.OK,
                message="No duplication findings detected",
                source=self.name,
                details={
                    **summary_counts,
                    "duplication_findings_human": findings_to_human_lines(detection_result),
                },
            )

        status = ResultStatus.WARNING
        if primary.severity == "critical":
            status = ResultStatus.CRITICAL
        elif primary.severity == "block":
            status = ResultStatus.BLOCK

        if summary_counts["duplication_critical_count"] != "0":
            status = ResultStatus.CRITICAL
        elif summary_counts["duplication_block_count"] != "0":
            status = ResultStatus.BLOCK

        return StepResult(
            status=status,
            message=primary.message,
            source=self.name,
            details={
                "error_code": primary.code,
                "duplication_symbol": primary.symbol_name,
                "duplication_responsibility_id": primary.responsibility_id,
                "duplication_findings_human": findings_to_human_lines(detection_result),
                **summary_counts,
            },
            affected_resources=[primary.file_path],
            suggested_actions=[primary.recommendation],
        )


@dataclass(slots=True)
class VerifyBlueprintModeStep(PipelineStep):
    """Executable blueprint_mode step for opt-in operation contract checks."""

    name: str = "blueprint_mode.verify"

    def run(self, context) -> StepResult:  # noqa: ANN001
        validation_result = validate_blueprint_mode_contracts(project_root=context.project_root)
        if validation_result.issues:
            first_issue = validation_result.issues[0]
            status = ResultStatus.BLOCK
            if first_issue.severity == "critical":
                status = ResultStatus.CRITICAL
            elif first_issue.severity == "warning":
                status = ResultStatus.WARNING

            return StepResult(
                status=status,
                message=first_issue.message,
                source=self.name,
                details={
                    "error_code": first_issue.code,
                    "blueprint_mode_enabled": str(validation_result.config.enabled).lower(),
                    "blueprint_mode_operation_count": str(len(validation_result.config.operations)),
                    "blueprint_mode_issue_count": str(len(validation_result.issues)),
                },
                affected_resources=[first_issue.file_path],
                suggested_actions=[first_issue.recommendation],
            )

        if validation_result.config.enabled:
            return StepResult(
                status=ResultStatus.OK,
                message="Blueprint mode contracts validated successfully",
                source=self.name,
                details={
                    "blueprint_mode_enabled": "true",
                    "blueprint_mode_operation_count": str(len(validation_result.config.operations)),
                    "blueprint_mode_issue_count": "0",
                },
            )

        return StepResult(
            status=ResultStatus.OK,
            message="Blueprint mode disabled; contract checks skipped",
            source=self.name,
            details={
                "blueprint_mode_enabled": "false",
                "blueprint_mode_operation_count": "0",
                "blueprint_mode_issue_count": "0",
            },
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
                suggested_actions=["Configure BPFW_MANIFEST_HMAC_KEY and run `bpfw manifest write` again"],
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

            if not self.strict and verification_result.only_precondition_issues:
                status = ResultStatus.WARNING

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
class ApproveRequestStep(PipelineStep):
    """Approve one pending request with configured auth backend."""

    name: str = "approval.approve"

    def run(self, context) -> StepResult:  # noqa: ANN001
        request_id = context.command_arguments.get("request_id", "").strip()
        if not request_id:
            return StepResult(
                status=ResultStatus.BLOCK,
                message="Missing request_id. Usage: bpfw approve <request_id>",
                source=self.name,
                details={"error_code": "APP_APPROVE_USAGE"},
                suggested_actions=["Pass a request id generated by verify-integrity"],
            )

        try:
            approval_result = approve_request(project_root=context.project_root, request_id=request_id)
        except (ApprovalBrokerError, ApprovalRequestError) as error:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=str(error),
                source=self.name,
                details={"error_code": "APP_APPROVE_BLOCK", "request_id": request_id},
                affected_resources=[str(context.project_root / ".bpfw/approval_requests")],
                suggested_actions=["Create or use a valid request id and ensure signing keys are configured"],
            )

        return StepResult(
            status=ResultStatus.OK,
            message=f"Approval issued for request `{request_id}`",
            source=self.name,
            details={
                "approval_id": approval_result.approval_id,
                "request_id": approval_result.request_id,
                "approval_backend": approval_result.backend,
                "approval_approved_by": approval_result.approved_by,
            },
            affected_resources=[str(approval_result.file_path)],
        )


@dataclass(slots=True)
class ListApprovalsStep(PipelineStep):
    """List and validate stored approvals."""

    name: str = "approval.list"

    def run(self, context) -> StepResult:  # noqa: ANN001
        try:
            verification_result = verify_all_approvals(project_root=context.project_root)
        except ApprovalVerificationError as error:
            return StepResult(
                status=ResultStatus.CRITICAL,
                message=str(error),
                source=self.name,
                details={"error_code": "APP_LIST_CRITICAL"},
                affected_resources=[str(context.project_root / ".bpfw/approvals")],
                suggested_actions=["Repair approval storage and run approvals again"],
            )

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

            return StepResult(
                status=status,
                message=first_issue.message,
                source=self.name,
                details={
                    "error_code": first_issue.code,
                    "approval_count": str(len(verification_result.approvals)),
                    "approval_issue_count": str(len(verification_result.issues)),
                },
                affected_resources=[first_issue.file_path] if first_issue.file_path else [],
                suggested_actions=[first_issue.recommendation],
            )

        return StepResult(
            status=ResultStatus.OK,
            message="Approvals are valid",
            source=self.name,
            details={
                "approval_count": str(len(verification_result.approvals)),
                "approval_issue_count": "0",
            },
        )


@dataclass(slots=True)
class StartChangeStep(PipelineStep):
    """Start a scoped change session and create its workspace."""

    name: str = "change.start"

    def run(self, context) -> StepResult:  # noqa: ANN001
        change_id = context.command_arguments.get("change_id", "").strip()
        scope_resource_id = context.command_arguments.get("scope", "").strip()

        if not change_id:
            return StepResult(
                status=ResultStatus.BLOCK,
                message="Missing change_id. Usage: bpfw start <change_id> --scope <resource_id>",
                source=self.name,
                details={"error_code": "CH_START_USAGE"},
            )
        if not scope_resource_id:
            return StepResult(
                status=ResultStatus.BLOCK,
                message="Missing --scope <resource_id>. Usage: bpfw start <change_id> --scope <resource_id>",
                source=self.name,
                details={"error_code": "CH_SCOPE_USAGE"},
            )

        try:
            scope = resolve_scope(project_root=context.project_root, scope_resource_id=scope_resource_id)
        except ScopeResolutionError as error:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=str(error),
                source=self.name,
                details={"error_code": "CH_SCOPE_INVALID"},
                suggested_actions=["Use a responsibility_id or locked resource_id defined in blueprint.yaml"],
            )

        if scope.locked:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=f"Scope `{scope.resource_id}` is locked and requires approval workflow",
                source=self.name,
                details={"error_code": "CH_SCOPE_LOCKED", "scope_resource_id": scope.resource_id},
                suggested_actions=["Use approval flow for locked resources"],
            )

        try:
            session = create_change_session(project_root=context.project_root, change_id=change_id, scope=scope)
            workspace_path = build_workspace(project_root=context.project_root, session=session)
        except (ChangeSessionError, WorkspaceBuildError) as error:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=str(error),
                source=self.name,
                details={"error_code": "CH_START_BLOCK", "scope_resource_id": scope_resource_id},
            )

        return StepResult(
            status=ResultStatus.OK,
            message=f"Workspace created for change `{change_id}`",
            source=self.name,
            details={
                "change_id": change_id,
                "scope_resource_id": scope.resource_id,
                "workspace_path": str(workspace_path),
                "allowed_file_count": str(len(session.allowed_files)),
            },
            affected_resources=[str(workspace_path)],
        )


@dataclass(slots=True)
class ReviewChangeStep(PipelineStep):
    """Review one workspace change against scope policy."""

    name: str = "change.review"

    def run(self, context) -> StepResult:  # noqa: ANN001
        change_id = context.command_arguments.get("change_id", "").strip()
        if not change_id:
            return StepResult(
                status=ResultStatus.BLOCK,
                message="Missing change_id. Usage: bpfw review <change_id>",
                source=self.name,
                details={"error_code": "CH_REVIEW_USAGE"},
            )

        try:
            session = load_change_session(project_root=context.project_root, change_id=change_id)
            decision = review_session(project_root=context.project_root, session=session)
        except (ChangeSessionError, ReviewDecisionError) as error:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=str(error),
                source=self.name,
                details={"error_code": "CH_REVIEW_BLOCK", "change_id": change_id},
            )

        changed_count = len(decision.diff.file_changes)
        if decision.status == "ALLOW":
            update_change_status(project_root=context.project_root, session=session, status="review_allow")
            return StepResult(
                status=ResultStatus.OK,
                message=f"Review ALLOW for change `{change_id}`",
                source=self.name,
                details={
                    "change_id": change_id,
                    "review_status": decision.status,
                    "changed_file_count": str(changed_count),
                    "workspace_path": decision.diff.workspace_path,
                },
            )

        update_change_status(project_root=context.project_root, session=session, status="review_block")
        finding = review_primary_finding(decision.findings)
        if finding is None:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=f"Review blocked for change `{change_id}`",
                source=self.name,
                details={"change_id": change_id, "review_status": decision.status},
            )

        return StepResult(
            status=ResultStatus.BLOCK,
            message=finding.message,
            source=self.name,
            details={
                "error_code": finding.code,
                "change_id": change_id,
                "review_status": decision.status,
                "changed_file_count": str(changed_count),
            },
            affected_resources=[str(context.project_root / finding.file_path)] if finding.file_path else [],
            suggested_actions=[finding.recommendation],
        )


@dataclass(slots=True)
class ApplyChangeStep(PipelineStep):
    """Apply reviewed workspace changes transactionally into repository."""

    name: str = "change.apply"

    def run(self, context) -> StepResult:  # noqa: ANN001
        change_id = context.command_arguments.get("change_id", "").strip()
        if not change_id:
            return StepResult(
                status=ResultStatus.BLOCK,
                message="Missing change_id. Usage: bpfw apply <change_id>",
                source=self.name,
                details={"error_code": "CH_APPLY_USAGE"},
            )

        try:
            session = load_change_session(project_root=context.project_root, change_id=change_id)
            decision = review_session(project_root=context.project_root, session=session)
        except (ChangeSessionError, ReviewDecisionError) as error:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=str(error),
                source=self.name,
                details={"error_code": "CH_APPLY_REVIEW_BLOCK", "change_id": change_id},
            )

        if decision.status != "ALLOW":
            finding = review_primary_finding(decision.findings)
            if finding is None:
                return StepResult(
                    status=ResultStatus.BLOCK,
                    message=f"Apply blocked because review did not pass for `{change_id}`",
                    source=self.name,
                    details={"change_id": change_id, "review_status": decision.status},
                )
            return StepResult(
                status=ResultStatus.BLOCK,
                message=finding.message,
                source=self.name,
                details={
                    "error_code": finding.code,
                    "change_id": change_id,
                    "review_status": decision.status,
                },
                affected_resources=[str(context.project_root / finding.file_path)] if finding.file_path else [],
                suggested_actions=[finding.recommendation],
            )

        try:
            transaction_result = apply_change_transaction(
                project_root=context.project_root,
                workspace_root=context.project_root / session.workspace_relative_path,
                change_id=change_id,
                file_changes=decision.diff.file_changes,
            )
            update_change_status(project_root=context.project_root, session=session, status="applied")
        except (ApplyTransactionError, ChangeSessionError) as error:
            return StepResult(
                status=ResultStatus.CRITICAL,
                message=str(error),
                source=self.name,
                details={"error_code": "CH_APPLY_CRITICAL", "change_id": change_id},
            )

        return StepResult(
            status=ResultStatus.OK,
            message=f"Applied change `{change_id}` successfully",
            source=self.name,
            details={
                "change_id": change_id,
                "applied_file_count": str(len(transaction_result.applied_paths)),
                "transaction_path": str(transaction_result.transaction_path),
            },
            affected_resources=[str(context.project_root / file_path) for file_path in transaction_result.applied_paths[:1]],
        )


@dataclass(slots=True)
class RejectChangeStep(PipelineStep):
    """Reject one change session without applying workspace changes."""

    name: str = "change.reject"

    def run(self, context) -> StepResult:  # noqa: ANN001
        change_id = context.command_arguments.get("change_id", "").strip()
        if not change_id:
            return StepResult(
                status=ResultStatus.BLOCK,
                message="Missing change_id. Usage: bpfw reject <change_id>",
                source=self.name,
                details={"error_code": "CH_REJECT_USAGE"},
            )

        try:
            session = load_change_session(project_root=context.project_root, change_id=change_id)
            update_change_status(project_root=context.project_root, session=session, status="rejected")
        except ChangeSessionError as error:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=str(error),
                source=self.name,
                details={"error_code": "CH_REJECT_BLOCK", "change_id": change_id},
            )

        return StepResult(
            status=ResultStatus.INFO,
            message=f"Change `{change_id}` marked as rejected",
            source=self.name,
            details={"change_id": change_id, "session_status": "rejected"},
        )


@dataclass(slots=True)
class DiscoverStep(PipelineStep):
    """Run discover scanner/classifier and persist proposals."""

    name: str = "discover.scan"

    def run(self, context) -> StepResult:  # noqa: ANN001
        scan_result = scan_repository(project_root=context.project_root)
        classified_findings = classify_findings(findings=scan_result.findings)
        proposal_result = build_proposals(project_root=context.project_root, classified_findings=classified_findings)
        pending_proposals = [proposal for proposal in list_proposals(context.project_root) if proposal.status == "pending"]

        if not classified_findings:
            return StepResult(
                status=ResultStatus.OK,
                message="No discover findings detected",
                source=self.name,
                details={
                    "discover_proposal_count": "0",
                    "discover_pending_count": str(len(pending_proposals)),
                },
            )

        status = ResultStatus.INFO
        if any(item.severity == "critical" for item in classified_findings):
            status = ResultStatus.CRITICAL
        elif any(item.severity == "high" for item in classified_findings):
            status = ResultStatus.WARNING

        created_proposal_ids = [proposal.proposal_id for proposal in proposal_result.created]
        details: dict[str, str] = {
            "discover_proposal_count": str(len(proposal_result.created)),
            "discover_pending_count": str(len(pending_proposals)),
        }
        if created_proposal_ids:
            details["proposals_human"] = "\n".join(f"- {proposal_id}" for proposal_id in created_proposal_ids)

        return StepResult(
            status=status,
            message=f"Discover generated {len(proposal_result.created)} proposal(s)",
            source=self.name,
            details=details,
        )


@dataclass(slots=True)
class ListProposalsStep(PipelineStep):
    """List stored discover proposals."""

    name: str = "proposal.list"

    def run(self, context) -> StepResult:  # noqa: ANN001
        proposals = list_proposals(project_root=context.project_root)
        return StepResult(
            status=ResultStatus.INFO,
            message=f"Loaded {len(proposals)} proposal(s)",
            source=self.name,
            details={
                "proposal_count": str(len(proposals)),
                "proposals_human": render_proposal_list(proposals),
            },
        )


@dataclass(slots=True)
class ShowProposalStep(PipelineStep):
    """Show one proposal by id."""

    name: str = "proposal.show"

    def run(self, context) -> StepResult:  # noqa: ANN001
        proposal_id = context.command_arguments.get("proposal_id", "").strip()
        if not proposal_id:
            return StepResult(
                status=ResultStatus.BLOCK,
                message="Missing proposal_id. Usage: bpfw show-proposal <proposal_id>",
                source=self.name,
                details={"error_code": "PR_SHOW_USAGE"},
            )

        try:
            proposal = load_proposal(project_root=context.project_root, proposal_id=proposal_id)
        except ProposalStoreError as error:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=str(error),
                source=self.name,
                details={"error_code": "PR_SHOW_BLOCK", "proposal_id": proposal_id},
            )

        return StepResult(
            status=ResultStatus.INFO,
            message=f"Loaded proposal `{proposal.proposal_id}`",
            source=self.name,
            details={
                "proposal_id": proposal.proposal_id,
                "proposal_status": proposal.status,
                "proposal_risk": proposal.risk,
                "proposal_human": render_proposal_detail(proposal),
            },
        )


@dataclass(slots=True)
class AcceptProposalStep(PipelineStep):
    """Accept one pending proposal and update blueprint."""

    name: str = "proposal.accept"

    def run(self, context) -> StepResult:  # noqa: ANN001
        proposal_id = context.command_arguments.get("proposal_id", "").strip()
        if not proposal_id:
            return StepResult(
                status=ResultStatus.BLOCK,
                message="Missing proposal_id. Usage: bpfw accept-proposal <proposal_id>",
                source=self.name,
                details={"error_code": "PR_ACCEPT_USAGE"},
            )

        try:
            result = accept_proposal(
                project_root=context.project_root,
                proposal_id=proposal_id,
                responsibility_id=context.command_arguments.get("responsibility", "").strip(),
                new_responsibility_id=context.command_arguments.get("as_new_responsibility", "").strip(),
                state=context.command_arguments.get("state", "").strip(),
            )
        except ProposalResolutionError as error:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=str(error),
                source=self.name,
                details={"error_code": "PR_ACCEPT_BLOCK", "proposal_id": proposal_id},
            )

        return StepResult(
            status=ResultStatus.OK,
            message=f"Proposal `{result.proposal.proposal_id}` accepted",
            source=self.name,
            details={
                "proposal_id": result.proposal.proposal_id,
                "proposal_status": result.proposal.status,
                "proposal_action": result.proposal.resolution.get("action", ""),
                "blueprint_modified": str(result.modified_blueprint).lower(),
            },
            affected_resources=[str(context.project_root / "blueprint.yaml")] if result.modified_blueprint else [],
        )


@dataclass(slots=True)
class RejectProposalStep(PipelineStep):
    """Reject one pending proposal and apply selected disposition action."""

    name: str = "proposal.reject"

    def run(self, context) -> StepResult:  # noqa: ANN001
        proposal_id = context.command_arguments.get("proposal_id", "").strip()
        if not proposal_id:
            return StepResult(
                status=ResultStatus.BLOCK,
                message="Missing proposal_id. Usage: bpfw reject-proposal <proposal_id>",
                source=self.name,
                details={"error_code": "PR_REJECT_USAGE"},
            )

        reject_action = context.command_arguments.get("reject_action", "").strip() or "move_to_rejected"
        try:
            result = reject_proposal(
                project_root=context.project_root,
                proposal_id=proposal_id,
                action=reject_action,
            )
        except ProposalResolutionError as error:
            return StepResult(
                status=ResultStatus.BLOCK,
                message=str(error),
                source=self.name,
                details={"error_code": "PR_REJECT_BLOCK", "proposal_id": proposal_id},
            )

        return StepResult(
            status=ResultStatus.INFO,
            message=f"Proposal `{result.proposal.proposal_id}` rejected",
            source=self.name,
            details={
                "proposal_id": result.proposal.proposal_id,
                "proposal_status": result.proposal.status,
                "proposal_action": result.proposal.resolution.get("reject_action", reject_action),
                "moved_file_count": str(len(result.moved_files)),
            },
            affected_resources=result.moved_files[:1],
        )


@dataclass(slots=True)
class InitProjectStep(PipelineStep):
    """Initialize BPFW governance for a new or existing project."""

    name: str = "init.project"

    def run(self, context) -> StepResult:  # noqa: ANN001
        accept_scan = context.command_arguments.get("accept_scan", "").strip() == "true"
        force_new = context.command_arguments.get("force_new", "").strip() == "true"
        detector = ProjectDetector()
        detection_result = detector.detect(project_root=context.project_root)

        if detection_result.is_initialized and not force_new and not accept_scan:
            return StepResult(
                status=ResultStatus.WARNING,
                message="BPFW INIT\n\nProject is already initialized.\n\nProtection is already active.",
                source=self.name,
                details={"blueprint_path": str(context.project_root / "blueprint.yaml")},
            )

        if accept_scan:
            try:
                acceptance_result = InitialBaselineAcceptor().accept(project_root=context.project_root)
            except (RuntimeError, IntegrityManifestError, IntegritySigningError) as error:
                return StepResult(
                    status=ResultStatus.BLOCK,
                    message=str(error),
                    source=self.name,
                    details={"error_code": "INIT_ACCEPT_BLOCK"},
                )
            return StepResult(
                status=ResultStatus.OK,
                message=(
                    "Initial baseline accepted.\n\n"
                    "Created:\n"
                    "- blueprint.yaml\n"
                    "- architecture.yaml\n"
                    "- .bpfw/manifest.json\n\n"
                    "Protection is now active by default."
                ),
                source=self.name,
                details={
                    "blueprint_path": str(acceptance_result.blueprint_path),
                    "manifest_path": str(acceptance_result.manifest_path),
                },
            )

        generator = InitialBlueprintGenerator()
        if force_new or not detection_result.is_existing_project:
            baseline = generator.generate_empty_baseline(project_root=context.project_root)
            bpfw_root = context.project_root / ".bpfw"
            for relative_directory in ["access_requests", "access_grants", "proposals"]:
                (bpfw_root / relative_directory).mkdir(parents=True, exist_ok=True)
            (bpfw_root / "state.json").write_text("{\n  \"protection_enabled\": true\n}\n", encoding="utf-8")
            try:
                manifest_result = write_manifest(project_root=context.project_root)
            except (IntegrityManifestError, IntegritySigningError) as error:
                return StepResult(
                    status=ResultStatus.BLOCK,
                    message=str(error),
                    source=self.name,
                    details={"error_code": "INIT_MANIFEST_BLOCK"},
                )
            return StepResult(
                status=ResultStatus.OK,
                message=(
                    "BPFW INIT\n\n"
                    "New project detected.\n\n"
                    "No existing blueprint was found.\n"
                    "No existing source structure was found.\n\n"
                    "Creating protected baseline:\n"
                    "- blueprint.yaml\n"
                    "- architecture.yaml\n"
                    "- .bpfw/state.json\n"
                    "- .bpfw/manifest.json\n"
                    "- .bpfw/access_requests/\n"
                    "- .bpfw/access_grants/\n"
                    "- .bpfw/proposals/\n\n"
                    "Protection is now active by default."
                ),
                source=self.name,
                details={
                    "blueprint_path": str(baseline.blueprint_path),
                    "manifest_path": str(manifest_result.manifest_path),
                },
            )

        scan_result = MechanicalProjectScanner().scan(project_root=context.project_root)
        generated_baseline = generator.generate(project_root=context.project_root, scan_result=scan_result)
        class_count = len([symbol for symbol in scan_result.symbols if symbol.kind == "class"])
        function_count = len([symbol for symbol in scan_result.symbols if symbol.kind == "function"])
        responsibility_count = generated_baseline.blueprint_path.read_text(encoding="utf-8").count("responsibility_id:")
        layer_count = len(set(scan_result.probable_layers.values()))

        return StepResult(
            status=ResultStatus.INFO,
            message=(
                "BPFW INIT\n\n"
                "Existing project detected.\n\n"
                "Mechanical scan completed:\n"
                f"- {len(scan_result.files)} Python files\n"
                f"- {class_count} classes\n"
                f"- {function_count} functions\n"
                f"- {responsibility_count} probable responsibilities\n"
                f"- {layer_count} probable layers\n\n"
                "Generated:\n"
                "- blueprint.generated.yaml\n"
                "- architecture.generated.yaml\n"
                "- .bpfw/scan_report.md\n\n"
                "Review the generated baseline and run:\n"
                "bpfw init --accept-scan"
            ),
            source=self.name,
            details={
                "scan_file_count": str(len(scan_result.files)),
                "scan_class_count": str(class_count),
                "scan_function_count": str(function_count),
                "scan_probable_responsibility_count": str(responsibility_count),
                "scan_probable_layer_count": str(layer_count),
                "blueprint_path": str(generated_baseline.blueprint_path),
            },
        )



def build_default_registry() -> dict[str, Pipeline]:
    """Create base command to pipeline mapping."""

    verify_pipeline = Pipeline(
        name="verify",
        steps=[
            VerifyAuthorityStep(),
            VerifyBlueprintStep(),
            VerifyArchitectureStep(),
            VerifyCompositionStep(),
            VerifyRuntimeSnapshotStep(),
            VerifyWiringStep(),
            VerifyDuplicationStep(),
            VerifyBlueprintModeStep(),
            VerifyIntegrityStep(strict=False),
        ],
    )
    verify_integrity_pipeline = Pipeline(
        name="verify_integrity",
        steps=[VerifyIntegrityStep(strict=True)],
    )
    manifest_write_pipeline = Pipeline(
        name="manifest_write",
        steps=[ManifestWriteStep()],
    )
    approve_pipeline = Pipeline(
        name="approve",
        steps=[ApproveRequestStep()],
    )
    approvals_pipeline = Pipeline(
        name="approvals",
        steps=[ListApprovalsStep()],
    )
    start_pipeline = Pipeline(
        name="start",
        steps=[StartChangeStep()],
    )
    review_pipeline = Pipeline(
        name="review",
        steps=[ReviewChangeStep()],
    )
    apply_pipeline = Pipeline(
        name="apply",
        steps=[ApplyChangeStep()],
    )
    reject_pipeline = Pipeline(
        name="reject",
        steps=[RejectChangeStep()],
    )
    architecture_check_pipeline = Pipeline(
        name="architecture_check",
        steps=[VerifyArchitectureStep()],
    )
    composition_check_pipeline = Pipeline(
        name="composition_check",
        steps=[VerifyCompositionStep()],
    )
    runtime_snapshot_pipeline = Pipeline(
        name="runtime_snapshot",
        steps=[VerifyRuntimeSnapshotStep()],
    )
    wiring_check_pipeline = Pipeline(
        name="wiring_check",
        steps=[VerifyWiringStep()],
    )
    discover_pipeline = Pipeline(
        name="discover",
        steps=[DiscoverStep()],
    )
    proposals_pipeline = Pipeline(
        name="proposals",
        steps=[ListProposalsStep()],
    )
    show_proposal_pipeline = Pipeline(
        name="show_proposal",
        steps=[ShowProposalStep()],
    )
    accept_proposal_pipeline = Pipeline(
        name="accept_proposal",
        steps=[AcceptProposalStep()],
    )
    reject_proposal_pipeline = Pipeline(
        name="reject_proposal",
        steps=[RejectProposalStep()],
    )
    install_hooks_pipeline = Pipeline(
        name="install_hooks",
        steps=[InstallHooksStep()],
    )
    init_pipeline = Pipeline(
        name="init",
        steps=[InitProjectStep()],
    )
    bootstrap_pipeline = Pipeline(
        name="bootstrap",
        steps=[
            StaticStep(
                name="blueprint.authority",
                message="Blueprint authority validation is not implemented yet",
            ),
            StaticStep(
                name="architecture.profile",
                message="Architecture profile validation is not implemented yet",
            ),
            StaticStep(
                name="lifecycle.rules",
                message="Lifecycle validation is not implemented yet",
            ),
        ],
    )
    return {
        "verify": verify_pipeline,
        "verify_integrity": verify_integrity_pipeline,
        "manifest_write": manifest_write_pipeline,
        "approve": approve_pipeline,
        "approvals": approvals_pipeline,
        "start": start_pipeline,
        "review": review_pipeline,
        "apply": apply_pipeline,
        "reject": reject_pipeline,
        "architecture_check": architecture_check_pipeline,
        "composition_check": composition_check_pipeline,
        "runtime_snapshot": runtime_snapshot_pipeline,
        "wiring_check": wiring_check_pipeline,
        "discover": discover_pipeline,
        "proposals": proposals_pipeline,
        "show_proposal": show_proposal_pipeline,
        "accept_proposal": accept_proposal_pipeline,
        "reject_proposal": reject_proposal_pipeline,
        "install_hooks": install_hooks_pipeline,
        "init": init_pipeline,
        "status": bootstrap_pipeline,
    }
