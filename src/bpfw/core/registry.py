"""Command registry for BPFW engine pipelines."""

from __future__ import annotations

from dataclasses import dataclass

from bpfw.apply.transaction import ApplyTransactionError, apply_change_transaction
from bpfw.approval.broker import ApprovalBrokerError, approve_request
from bpfw.approval.request import ApprovalRequestError
from bpfw.approval.verifier import ApprovalVerificationError, verify_all_approvals
from bpfw.architecture.architecture_validator import validate_architecture
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
from bpfw.duplication.duplication_reporter import (
    findings_to_human_lines,
    primary_finding,
    summarize_counts,
)
from bpfw.duplication.similarity_detector import detect_duplication
from bpfw.integrity.manifest import IntegrityManifestError, write_manifest
from bpfw.integrity.signer import IntegritySigningError
from bpfw.integrity.verifier import verify_integrity
from bpfw.review.decision import ReviewDecisionError, primary_finding, review_session
from bpfw.runtime.collector import collect_runtime_snapshot
from bpfw.runtime.snapshot import snapshot_to_dict, snapshot_to_human_lines, snapshot_to_json
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
        primary = primary_finding(detection_result)
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
        finding = primary_finding(decision.findings)
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
            finding = primary_finding(decision.findings)
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



def build_default_registry() -> dict[str, Pipeline]:
    """Create base command to pipeline mapping."""

    verify_pipeline = Pipeline(
        name="verify",
        steps=[
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
        steps=[VerifyDuplicationStep()],
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
        "status": bootstrap_pipeline,
    }
