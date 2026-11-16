"""Execute deep evidence using the managed PipeCraft runtime."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from bpfw.core.catalog.domain.models import BlueprintDocument
from bpfw.core.evidence.fingerprint import fingerprint_evidence
from bpfw.core.evidence.models import EvidenceRecord, EvidenceRequirement
from bpfw.core.evidence.requirements import collect_evidence_requirements
from bpfw.core.evidence.store import EvidenceStore, EvidenceStoreCorruption
from bpfw.core.scenarios import load_scenarios
from bpfw.runtime.pipecraft.client import PipeCraftClient
from bpfw.runtime.pipecraft.compiler import PipeCraftEvidenceCompiler
from bpfw.reports.finding import Finding


class EvidenceRunner:
    """Execute and persist runtime evidence without allowing infrastructure failures to escape as false PASSes."""

    def __init__(self, project_root: Path, client: PipeCraftClient | None = None) -> None:
        self.project_root = project_root.resolve()
        self.client = client or PipeCraftClient()
        self.compiler = PipeCraftEvidenceCompiler(self.project_root)
        self.store = EvidenceStore(self.project_root)

    @staticmethod
    def fingerprint(document: BlueprintDocument, project_root: Path) -> str:
        return fingerprint_evidence(document, project_root)

    @staticmethod
    def _new_operation_id() -> str:
        return f"ev-{uuid4().hex[:12]}"

    @staticmethod
    def _exception_finding(
        *,
        code: str,
        stage: str,
        message: str,
        error: Exception,
        invariant_ids: tuple[str, ...],
        operation_id: str,
    ) -> Finding:
        return Finding(
            source="evidence",
            code=code,
            severity="block",
            message=message,
            affected_invariants=invariant_ids,
            category="behavioral_drift",
            confidence="high",
            evidence={
                "operation_id": operation_id,
                "stage": stage,
                "error_type": type(error).__name__,
                "error": str(error),
            },
        )

    def _fingerprint_or_finding(
        self,
        document: BlueprintDocument,
        operation_id: str,
    ) -> tuple[str | None, list[Finding]]:
        try:
            return self.fingerprint(document, self.project_root), []
        except Exception as error:  # noqa: BLE001 - boundary must convert failures to findings.
            return None, [self._exception_finding(
                code="EVIDENCE_FINGERPRINT_FAILED",
                stage="fingerprint",
                message="BPFW could not fingerprint the current evidence inputs; dynamic evidence cannot be trusted.",
                error=error,
                invariant_ids=(),
                operation_id=operation_id,
            )]

    def freshness_findings(self, document: BlueprintDocument) -> list[Finding]:
        """Report missing or stale dynamic evidence without executing anything."""
        operation_id = self._new_operation_id()
        fingerprint, fingerprint_findings = self._fingerprint_or_finding(document, operation_id)
        if fingerprint is None:
            return fingerprint_findings

        findings: list[Finding] = []
        seen: set[str] = set()
        for requirement in collect_evidence_requirements(document):
            if requirement.invariant_id in seen:
                continue
            seen.add(requirement.invariant_id)
            try:
                latest = self.store.latest(requirement.invariant_id)
            except EvidenceStoreCorruption as error:
                findings.append(Finding(
                    source="evidence", code="EVIDENCE_STORE_CORRUPT", severity="block",
                    message=(
                        "Stored dynamic evidence cannot be trusted because the evidence journal is corrupt. "
                        "Run deep verification to append fresh evidence after the damaged record or inspect the journal."
                    ),
                    affected_invariants=(requirement.invariant_id,), category="behavioral_drift",
                    evidence={
                        "operation_id": operation_id,
                        "journal_path": str(error.path),
                        "corrupt_line": error.line_number,
                        "suggested_command": "bpfw verify --deep",
                    },
                    confidence="high",
                ))
                continue
            if latest is None:
                findings.append(Finding(
                    source="evidence", code="EVIDENCE_MISSING", severity="warning",
                    message=f"Invariant '{requirement.invariant_id}' declares dynamic evidence but has not been verified yet.",
                    affected_invariants=(requirement.invariant_id,), category="behavioral_drift",
                    evidence={"operation_id": operation_id, "suggested_command": "bpfw verify --deep"},
                ))
            elif latest.status != "pass" or latest.fingerprint != fingerprint:
                findings.append(Finding(
                    source="evidence", code="EVIDENCE_STALE", severity="warning",
                    message=f"Dynamic evidence for invariant '{requirement.invariant_id}' is stale for the current project state.",
                    affected_invariants=(requirement.invariant_id,), category="behavioral_drift",
                    evidence={
                        "operation_id": operation_id,
                        "last_status": latest.status,
                        "last_fingerprint": latest.fingerprint,
                        "current_fingerprint": fingerprint,
                        "suggested_command": "bpfw verify --deep",
                    },
                ))
        return findings

    def _scenario_commands(
        self,
        requirement: EvidenceRequirement,
        document: BlueprintDocument,
    ) -> tuple[list[EvidenceRequirement], list[Finding]]:
        scenarios = load_scenarios(document)
        scenario = scenarios.get(requirement.scenario or "")
        if scenario is None:
            return [], [Finding(
                source="evidence", code="EVIDENCE_SCENARIO_UNKNOWN", severity="block",
                message=f"Invariant '{requirement.invariant_id}' references unknown scenario '{requirement.scenario}'.",
                affected_invariants=(requirement.invariant_id,), category="behavioral_drift",
            )]
        commands: list[EvidenceRequirement] = []
        for raw in scenario.evidence:
            if str(raw.get("type") or "").strip().lower() != "command":
                continue
            command = raw.get("command")
            if isinstance(command, list) and command and all(isinstance(part, str) and part for part in command):
                commands.append(EvidenceRequirement(
                    invariant_id=requirement.invariant_id,
                    kind="command",
                    command=tuple(command),
                    scenario=scenario.identifier,
                ))
        if not commands:
            return [], [Finding(
                source="evidence", code="EVIDENCE_SCENARIO_NOT_EXECUTABLE", severity="warning",
                message=f"Scenario evidence '{scenario.identifier}' has no structured command evidence plan.",
                affected_invariants=(requirement.invariant_id,), category="behavioral_drift",
            )]
        return commands, []

    def _prepare_requirement(
        self,
        requirement: EvidenceRequirement,
        operation_id: str,
    ) -> tuple[tuple[str, Path, dict] | None, list[Finding]]:
        invariant = (requirement.invariant_id,)
        try:
            pipeline, workspace = self.compiler.compile(requirement)
        except Exception as error:  # noqa: BLE001
            return None, [self._exception_finding(
                code="EVIDENCE_COMPILE_FAILED",
                stage="compile",
                message=f"BPFW could not compile evidence for invariant '{requirement.invariant_id}'.",
                error=error,
                invariant_ids=invariant,
                operation_id=operation_id,
            )]

        try:
            validation = self.client.validate(workspace, pipeline)
        except Exception as error:  # noqa: BLE001
            return None, [self._exception_finding(
                code="PIPECRAFT_VALIDATE_ERROR",
                stage="pipecraft.validate",
                message=f"PipeCraft validation could not be executed for '{requirement.invariant_id}'.",
                error=error,
                invariant_ids=invariant,
                operation_id=operation_id,
            )]
        if not validation.success:
            return None, [Finding(
                source="evidence", code="PIPECRAFT_VALIDATION_FAILED", severity="block",
                message=f"PipeCraft could not validate evidence pipeline for '{requirement.invariant_id}'.",
                evidence={"operation_id": operation_id, "payload": validation.payload, "stderr": validation.stderr},
                affected_invariants=invariant, category="behavioral_drift",
            )]

        try:
            plan = self.client.plan(workspace, pipeline)
        except Exception as error:  # noqa: BLE001
            return None, [self._exception_finding(
                code="PIPECRAFT_PLAN_ERROR",
                stage="pipecraft.plan",
                message=f"PipeCraft planning could not be executed for '{requirement.invariant_id}'.",
                error=error,
                invariant_ids=invariant,
                operation_id=operation_id,
            )]
        if not plan.success:
            return None, [Finding(
                source="evidence", code="PIPECRAFT_PLAN_FAILED", severity="block",
                message=f"PipeCraft could not plan evidence for '{requirement.invariant_id}'.",
                evidence={"operation_id": operation_id, "payload": plan.payload, "stderr": plan.stderr},
                affected_invariants=invariant, category="behavioral_drift",
            )]
        return (pipeline, workspace, plan.payload), []

    def _persist_record(self, record: EvidenceRecord, operation_id: str) -> list[Finding]:
        try:
            self.store.append(record)
        except Exception as error:  # noqa: BLE001
            return [self._exception_finding(
                code="EVIDENCE_PERSIST_FAILED",
                stage="evidence.persist",
                message=f"Runtime evidence for invariant '{record.invariant_id}' ran but could not be persisted safely.",
                error=error,
                invariant_ids=(record.invariant_id,),
                operation_id=operation_id,
            )]
        return []

    def _execute_requirement(
        self,
        requirement: EvidenceRequirement,
        fingerprint: str,
        operation_id: str,
    ) -> tuple[EvidenceRecord | None, list[Finding]]:
        prepared, findings = self._prepare_requirement(requirement, operation_id)
        if prepared is None:
            return None, findings
        pipeline, workspace, plan_payload = prepared
        try:
            result = self.client.run(workspace, pipeline, execute=True)
        except Exception as error:  # noqa: BLE001
            return None, [self._exception_finding(
                code="PIPECRAFT_RUN_ERROR",
                stage="pipecraft.run",
                message=f"PipeCraft evidence execution could not run for '{requirement.invariant_id}'.",
                error=error,
                invariant_ids=(requirement.invariant_id,),
                operation_id=operation_id,
            )]

        status = "pass" if result.success else "fail"
        record = EvidenceRecord(
            invariant_id=requirement.invariant_id,
            status=status,
            fingerprint=fingerprint,
            timestamp=datetime.now(timezone.utc).isoformat(),
            pipeline=pipeline,
            run_id=result.payload.get("run_id"),
            scenario=requirement.scenario,
            report_path=result.payload.get("report_path"),
            events_path=result.payload.get("events_path"),
            stdout=result.stdout,
            stderr=result.stderr,
            operation_id=operation_id,
            details={"plan": plan_payload, "result": result.payload},
        )
        findings.extend(self._persist_record(record, operation_id))
        if not result.success:
            findings.append(Finding(
                source="evidence", code="DYNAMIC_EVIDENCE_FAILED", severity="block",
                message=f"Runtime evidence failed for invariant '{requirement.invariant_id}'.",
                evidence={
                    "operation_id": operation_id,
                    "run_id": record.run_id,
                    "report_path": record.report_path,
                    "stderr": result.stderr,
                },
                affected_invariants=(requirement.invariant_id,), category="behavioral_drift", confidence="high",
            ))
        return record, findings

    @staticmethod
    def _deduplicate_requirements(requirements: list[EvidenceRequirement]) -> list[EvidenceRequirement]:
        seen: set[tuple[str, str, tuple[str, ...], str | None]] = set()
        result: list[EvidenceRequirement] = []
        for requirement in requirements:
            key = (requirement.invariant_id, requirement.kind, requirement.command, requirement.scenario)
            if key in seen:
                continue
            seen.add(key)
            result.append(requirement)
        return result

    def run(self, document: BlueprintDocument) -> tuple[list[EvidenceRecord], list[Finding]]:
        operation_id = self._new_operation_id()
        records: list[EvidenceRecord] = []
        findings: list[Finding] = []
        fingerprint, fingerprint_findings = self._fingerprint_or_finding(document, operation_id)
        if fingerprint is None:
            return records, fingerprint_findings

        executable: list[EvidenceRequirement] = []
        for requirement in collect_evidence_requirements(document):
            if requirement.kind == "command":
                executable.append(requirement)
            elif requirement.kind == "scenario":
                try:
                    commands, scenario_findings = self._scenario_commands(requirement, document)
                except Exception as error:  # noqa: BLE001
                    findings.append(self._exception_finding(
                        code="EVIDENCE_SCENARIO_LOAD_FAILED",
                        stage="scenario.load",
                        message=f"BPFW could not load scenario evidence for '{requirement.invariant_id}'.",
                        error=error,
                        invariant_ids=(requirement.invariant_id,),
                        operation_id=operation_id,
                    ))
                    continue
                executable.extend(commands)
                findings.extend(scenario_findings)
        executable = self._deduplicate_requirements(executable)

        if len(executable) <= 1:
            for requirement in executable:
                record, execution_findings = self._execute_requirement(requirement, fingerprint, operation_id)
                if record is not None:
                    records.append(record)
                findings.extend(execution_findings)
            return records, findings

        prepared: list[tuple[EvidenceRequirement, str, Path, dict]] = []
        for requirement in executable:
            prepared_result, prepare_findings = self._prepare_requirement(requirement, operation_id)
            findings.extend(prepare_findings)
            if prepared_result is None:
                continue
            pipeline, workspace, plan_payload = prepared_result
            prepared.append((requirement, pipeline, workspace, plan_payload))

        if not prepared:
            return records, findings
        workspace = prepared[0][2]
        try:
            batch = self.client.run_many(
                workspace,
                [item[1] for item in prepared],
                execute=True,
                max_pipelines=min(4, len(prepared)),
                max_tasks=max(4, min(16, len(prepared) * 4)),
            )
        except Exception as error:  # noqa: BLE001
            findings.append(self._exception_finding(
                code="PIPECRAFT_BATCH_ERROR",
                stage="pipecraft.run-many",
                message="PipeCraft batch evidence execution could not be completed.",
                error=error,
                invariant_ids=tuple(item[0].invariant_id for item in prepared),
                operation_id=operation_id,
            ))
            return records, findings

        raw_runs = batch.payload.get("runs", [])
        if not isinstance(raw_runs, list):
            raw_runs = []
        run_items = {
            str(item.get("pipeline")): item
            for item in raw_runs
            if isinstance(item, dict) and item.get("pipeline")
        }
        explicit_success_count = 0
        for requirement, pipeline, _workspace, plan_payload in prepared:
            item = run_items.get(pipeline)
            if item is None:
                findings.append(Finding(
                    source="evidence", code="EVIDENCE_BATCH_RESULT_MISSING", severity="block",
                    message=f"PipeCraft batch output omitted the result for invariant '{requirement.invariant_id}'.",
                    evidence={"operation_id": operation_id, "pipeline": pipeline, "batch_returncode": batch.returncode},
                    affected_invariants=(requirement.invariant_id,), category="behavioral_drift", confidence="high",
                ))
                continue

            item_success = item.get("success")
            success = item_success if isinstance(item_success, bool) else False
            if success:
                explicit_success_count += 1
            status = "pass" if success else "fail"
            record = EvidenceRecord(
                invariant_id=requirement.invariant_id,
                status=status,
                fingerprint=fingerprint,
                timestamp=datetime.now(timezone.utc).isoformat(),
                pipeline=pipeline,
                run_id=item.get("run_id"),
                scenario=requirement.scenario,
                report_path=item.get("report_path"),
                events_path=item.get("events_path"),
                stdout=batch.stdout,
                stderr=batch.stderr,
                operation_id=operation_id,
                details={
                    "plan": plan_payload,
                    "result": item,
                    "batch": {"runtime": batch.payload.get("runtime"), "returncode": batch.returncode},
                },
            )
            findings.extend(self._persist_record(record, operation_id))
            records.append(record)
            if not success:
                findings.append(Finding(
                    source="evidence", code="DYNAMIC_EVIDENCE_FAILED", severity="block",
                    message=f"Runtime evidence failed for invariant '{requirement.invariant_id}'.",
                    evidence={
                        "operation_id": operation_id,
                        "run_id": record.run_id,
                        "report_path": record.report_path,
                        "stderr": batch.stderr,
                        "batch_returncode": batch.returncode,
                    },
                    affected_invariants=(requirement.invariant_id,), category="behavioral_drift", confidence="high",
                ))

        if batch.returncode != 0 and explicit_success_count == len(prepared):
            findings.append(Finding(
                source="evidence", code="PIPECRAFT_BATCH_STATUS_MISMATCH", severity="warning",
                message="PipeCraft returned a non-zero batch status even though every individual evidence run reported success.",
                evidence={"operation_id": operation_id, "batch_returncode": batch.returncode},
                affected_invariants=tuple(item[0].invariant_id for item in prepared),
                category="behavioral_drift",
            ))
        return records, findings
