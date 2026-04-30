"""Command registry for BPFW engine pipelines — MVP Catalog Mode."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from bpfw.authority.state import AuthorityState, UnlockWindow, load_authority_state, save_authority_state
from bpfw.blueprint.schema import CANONICAL_BLUEPRINT_FILE
from bpfw.blueprint.validator import validate_blueprint
from bpfw.catalog.verify import run_catalog_verify
from bpfw.catalog.wizard import complete_human_fields
from bpfw.core.pipeline import Pipeline, PipelineStep
from bpfw.core.result import ResultStatus, StepResult
from bpfw.init.detector import ProjectDetector
from bpfw.init.scanner import MechanicalProjectScanner


def _parse_ttl_to_minutes(raw_ttl: str) -> int:
    """Parse TTL string to minutes for unlock duration."""

    normalized_ttl = raw_ttl.strip().lower()
    if not normalized_ttl:
        raise ValueError("Missing --ttl value")
    if normalized_ttl.endswith("m"):
        return int(normalized_ttl[:-1] or "0")
    if normalized_ttl.endswith("h"):
        return int(normalized_ttl[:-1] or "0") * 60
    return int(normalized_ttl)


def _is_unlock_window_active(unlock_window: UnlockWindow | None) -> bool:
    """Check if unlock window is still valid."""

    if unlock_window is None:
        return False
    if unlock_window.resource_id != "project_blueprint":
        return False

    try:
        expiration_time = datetime.fromisoformat(unlock_window.expires_at)
    except ValueError:
        return False

    if expiration_time.tzinfo is None:
        expiration_time = expiration_time.replace(tzinfo=timezone.utc)

    return expiration_time > datetime.now(timezone.utc)


def _is_blueprint_locked(project_root: Path) -> bool:
    """Return lock state for blueprint authority resource."""

    authority_state = load_authority_state(project_root=project_root)
    return not _is_unlock_window_active(authority_state.active_unlock_window)


def _seed_blueprint_payload(project_root: Path) -> dict:
    """Create deterministic initial blueprint payload from mechanical scan."""

    scanner = MechanicalProjectScanner()
    scan_result = scanner.scan(project_root=project_root)

    symbols_by_file: dict[str, list[str]] = {}
    for symbol in scan_result.symbols:
        if symbol.kind in {"class", "function"}:
            symbols_by_file.setdefault(symbol.file_path, []).append(symbol.name)

    responsibilities_payload: list[dict] = []
    for file_index, file_path in enumerate(sorted(set(scan_result.files)), start=1):
        file_symbols = sorted(set(symbols_by_file.get(file_path, [])))
        if not file_symbols:
            continue

        responsibility_id = f"responsibility_{file_index:03d}"
        canonical_name = Path(file_path).stem.replace("_", " ").title().replace(" ", "")
        primary_symbol = file_symbols[0]
        implementation_id = f"{responsibility_id}_default"

        responsibilities_payload.append(
            {
                "responsibility_id": responsibility_id,
                "canonical_name": canonical_name or responsibility_id,
                "owner_layer": "application" if "/application/" in f"/{file_path}" else "domain",
                "intent": "",
                "lifecycle_state": "active",
                "allowed_files": [file_path],
                "allowed_symbols": file_symbols,
                "allowed_implementations": [
                    {
                        "implementation_id": implementation_id,
                        "class_name": primary_symbol,
                        "file": file_path,
                        "lifecycle_state": "active",
                        "replacement_id": None,
                        "disabled_reason": None,
                        "removal_plan": None,
                    }
                ],
                "active_implementation": implementation_id,
                "forbidden_duplicates": [],
                "mutability": "editable",
                "owner": "project_owner",
            }
        )

    return {
        "version": 1,
        "responsibilities": responsibilities_payload,
        "locked_resources": [
            {
                "resource_id": "project_blueprint",
                "path": CANONICAL_BLUEPRINT_FILE,
                "mutability": "locked",
                "owner": "project_owner",
            }
        ],
    }


@dataclass(slots=True)
class InitProjectStep(PipelineStep):
    """Initialize project with baseline blueprint for MVP."""

    name: str = "init.project"

    def run(self, context) -> StepResult:  # noqa: ANN001
        force_new = str(context.command_arguments.get("force_new", "")).strip().lower() == "true"

        detector = ProjectDetector()
        detection_result = detector.detect(project_root=context.project_root)
        if detection_result.is_initialized and not force_new:
            return StepResult(
                status=ResultStatus.WARNING,
                message="Project already initialized. Use --force-new to reinitialize.",
                source=self.name,
                details={"blueprint_path": str(context.project_root / CANONICAL_BLUEPRINT_FILE)},
            )

        blueprint_path = context.project_root / CANONICAL_BLUEPRINT_FILE
        blueprint_path.parent.mkdir(parents=True, exist_ok=True)
        payload = _seed_blueprint_payload(project_root=context.project_root)
        blueprint_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

        authority_state = AuthorityState(
            protection_enabled=True,
            os_lock_enabled=False,
            active_unlock_window=None,
            last_relock_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )
        save_authority_state(project_root=context.project_root, state=authority_state)

        return StepResult(
            status=ResultStatus.OK,
            message=f"BPFW initialized. Blueprint generated at {CANONICAL_BLUEPRINT_FILE}",
            source=self.name,
            details={
                "blueprint_path": str(blueprint_path),
                "responsibility_count": str(len(payload.get("responsibilities", []))),
            },
            affected_resources=[str(blueprint_path)],
        )


@dataclass(slots=True)
class WizardStep(PipelineStep):
    """Complete human fields in blueprint deterministically."""

    name: str = "wizard.complete"

    def run(self, context) -> StepResult:  # noqa: ANN001
        if _is_blueprint_locked(project_root=context.project_root):
            return StepResult(
                status=ResultStatus.BLOCK,
                message="BLOCK: Blueprint is locked. Run bpfw unlock before editing.",
                source=self.name,
                details={"error_code": "WIZARD_LOCKED"},
            )

        blueprint_path, updated_entries = complete_human_fields(project_root=context.project_root)
        return StepResult(
            status=ResultStatus.OK,
            message=f"Wizard completed. Updated fields: {updated_entries}",
            source=self.name,
            details={"blueprint_path": str(blueprint_path), "updated_fields": str(updated_entries)},
            affected_resources=[str(blueprint_path)],
        )


@dataclass(slots=True)
class VerifyBlueprintStep(PipelineStep):
    """Run catalog mode verify against blueprint and project code."""

    name: str = "catalog.verify"

    def run(self, context) -> StepResult:  # noqa: ANN001
        validation_result = validate_blueprint(project_root=context.project_root)
        if not validation_result.is_valid or validation_result.blueprint is None:
            first_error = validation_result.errors[0]
            return StepResult(
                status=ResultStatus.BLOCK,
                message=first_error.message,
                source=self.name,
                details={"error_code": first_error.code},
                affected_resources=[first_error.file_path],
                suggested_actions=[first_error.recommendation],
            )

        verify_result = run_catalog_verify(project_root=context.project_root, blueprint=validation_result.blueprint)

        blocked_findings = [finding for finding in verify_result.findings if finding.status == "block"]
        if blocked_findings:
            first_finding = blocked_findings[0]
            return StepResult(
                status=ResultStatus.BLOCK,
                message=first_finding.message,
                source=self.name,
                details={
                    "error_code": first_finding.code,
                    **verify_result.summary,
                    "blocking_reasons": str(len(blocked_findings)),
                },
                affected_resources=[first_finding.resource],
                suggested_actions=["Run bpfw wizard, update bpfw/blueprint.yaml, then run bpfw verify"],
            )

        message_text = "BPFW VERIFY PASSED"
        if validation_result.warnings:
            message_text = f"{message_text} (with migration warning)"

        return StepResult(
            status=ResultStatus.OK,
            message=message_text,
            source=self.name,
            details={**verify_result.summary, "blocking_reasons": "0"},
        )


@dataclass(slots=True)
class AuthorityLockStep(PipelineStep):
    """Lock blueprint authority resource."""

    name: str = "authority.lock"

    def run(self, context) -> StepResult:  # noqa: ANN001
        authority_state = load_authority_state(project_root=context.project_root)
        authority_state.active_unlock_window = None
        authority_state.last_relock_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        save_authority_state(project_root=context.project_root, state=authority_state)

        return StepResult(
            status=ResultStatus.OK,
            message=f"Blueprint locked: {CANONICAL_BLUEPRINT_FILE}",
            source=self.name,
            details={"lock_state": "locked", "resource_id": "project_blueprint"},
        )


@dataclass(slots=True)
class AuthorityUnlockStep(PipelineStep):
    """Unlock blueprint resource with TTL window."""

    name: str = "authority.unlock"

    def run(self, context) -> StepResult:  # noqa: ANN001
        ttl_minutes = _parse_ttl_to_minutes(context.command_arguments.get("ttl", "10m"))
        if ttl_minutes <= 0:
            return StepResult(
                status=ResultStatus.BLOCK,
                message="ttl must be greater than zero",
                source=self.name,
                details={"error_code": "AUTH_UNLOCK_TTL"},
            )

        expiration_time = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        unlock_window = UnlockWindow(
            resource_id="project_blueprint",
            resource_path=CANONICAL_BLUEPRINT_FILE,
            scope=str(context.command_arguments.get("scope", "manual") or "manual"),
            operation=str(context.command_arguments.get("operation", "unlock") or "unlock"),
            expires_at=expiration_time.replace(microsecond=0).isoformat(),
            granted_by="cli",
            request_id="",
            grant_id=f"manual_project_blueprint_{int(expiration_time.timestamp())}",
        )

        authority_state = load_authority_state(project_root=context.project_root)
        authority_state.active_unlock_window = unlock_window
        save_authority_state(project_root=context.project_root, state=authority_state)

        return StepResult(
            status=ResultStatus.OK,
            message=f"Blueprint unlocked for {ttl_minutes} minutes",
            source=self.name,
            details={"resource_id": "project_blueprint", "expires_at": unlock_window.expires_at},
        )


@dataclass(slots=True)
class AuthorityStatusStep(PipelineStep):
    """Report MVP status for lock, blueprint and catalog checks."""

    name: str = "authority.status"

    def run(self, context) -> StepResult:  # noqa: ANN001
        validation_result = validate_blueprint(project_root=context.project_root)
        lock_state = "locked" if _is_blueprint_locked(project_root=context.project_root) else "unlocked"

        if not validation_result.is_valid or validation_result.blueprint is None:
            first_error = validation_result.errors[0]
            return StepResult(
                status=ResultStatus.WARNING,
                message="Blueprint status reported with validation warnings",
                source=self.name,
                details={
                    "lock": lock_state,
                    "blueprint_state": "invalid",
                    "drift_state": "unknown",
                    "lifecycle_state": "unknown",
                    "first_error": first_error.code,
                },
            )

        verify_result = run_catalog_verify(project_root=context.project_root, blueprint=validation_result.blueprint)
        drift_state = "clean"
        lifecycle_state = "valid"
        if int(verify_result.summary.get("missing_declared_code", "0")) > 0 or int(verify_result.summary.get("undeclared_code", "0")) > 0:
            drift_state = "drift"
        if int(verify_result.summary.get("invalid_lifecycles", "0")) > 0:
            lifecycle_state = "invalid"

        return StepResult(
            status=ResultStatus.OK,
            message="MVP status reported",
            source=self.name,
            details={
                "lock": lock_state,
                "blueprint_state": "defined",
                "drift_state": drift_state,
                "lifecycle_state": lifecycle_state,
                **verify_result.summary,
            },
        )


def build_default_registry() -> dict[str, Pipeline]:
    """Build default pipeline registry for BPFW MVP."""

    return {
        "verify": Pipeline(name="verify", steps=[VerifyBlueprintStep()]),
        "lock": Pipeline(name="lock", steps=[AuthorityLockStep()]),
        "unlock": Pipeline(name="unlock", steps=[AuthorityUnlockStep()]),
        "status": Pipeline(name="status", steps=[AuthorityStatusStep()]),
        "init": Pipeline(name="init", steps=[InitProjectStep()]),
        "wizard": Pipeline(name="wizard", steps=[WizardStep()]),
    }
