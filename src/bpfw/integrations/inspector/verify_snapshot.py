"""Persistent verify snapshot cache for inspector startup fast paths."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bpfw.core.catalog.models import VerificationReport
from bpfw.reports.finding import Finding

_SCHEMA_VERSION = 1
_CACHE_RELATIVE_PATH = Path(".bpfw") / "cache" / "verify_snapshot.json"


@dataclass(frozen=True)
class VerifySnapshot:
    """Cached verify snapshot scoped to one authority+input signature."""

    input_signature: str
    authority_signature: str
    report: VerificationReport
    saved_at: str


class VerifySnapshotRepository:
    """Load and save reusable verify snapshots for inspector startup."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.path = self.project_root / _CACHE_RELATIVE_PATH

    def load(self, input_signature: str, authority_signature: str) -> VerifySnapshot | None:
        """Load a cached verify snapshot when signatures match."""
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("schema_version") != _SCHEMA_VERSION:
            return None
        if payload.get("input_signature") != input_signature:
            return None
        if payload.get("authority_signature") != authority_signature:
            return None
        report_data = payload.get("report")
        if not isinstance(report_data, dict):
            return None
        report = _report_from_json(report_data)
        if report is None:
            return None
        saved_at = str(payload.get("saved_at") or "").strip()
        return VerifySnapshot(
            input_signature=input_signature,
            authority_signature=authority_signature,
            report=report,
            saved_at=saved_at,
        )

    def save(
        self,
        input_signature: str,
        authority_signature: str,
        report: VerificationReport,
        saved_at: str,
    ) -> None:
        """Persist a verify snapshot for future strict cache reuse."""
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "input_signature": input_signature,
            "authority_signature": authority_signature,
            "saved_at": saved_at,
            "report": _report_to_json(report),
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        except OSError:
            return

    def invalidate(self) -> None:
        """Best-effort cache invalidation."""
        try:
            self.path.unlink()
        except (FileNotFoundError, OSError):
            return


def _report_to_json(report: VerificationReport) -> dict[str, Any]:
    return {
        "authority_state": report.authority_state,
        "allowed": report.allowed,
        "findings": [_finding_to_json(item) for item in report.findings],
        "declared_count": report.declared_count,
        "discovered_count": report.discovered_count,
        "missing_declared_count": report.missing_declared_count,
        "undeclared_count": report.undeclared_count,
        "duplicate_active_purpose_count": report.duplicate_active_purpose_count,
        "invalid_lifecycle_count": report.invalid_lifecycle_count,
        "incomplete_responsibility_count": report.incomplete_responsibility_count,
    }


def _report_from_json(data: dict[str, Any]) -> VerificationReport | None:
    findings_payload = data.get("findings")
    if not isinstance(findings_payload, list):
        return None
    findings: list[Finding] = []
    for item in findings_payload:
        if not isinstance(item, dict):
            continue
        findings.append(_finding_from_json(item))
    return VerificationReport(
        authority_state=str(data.get("authority_state", "missing")),
        allowed=bool(data.get("allowed", False)),
        findings=findings,
        declared_count=_safe_int(data.get("declared_count")),
        discovered_count=_safe_int(data.get("discovered_count")),
        missing_declared_count=_safe_int(data.get("missing_declared_count")),
        undeclared_count=_safe_int(data.get("undeclared_count")),
        duplicate_active_purpose_count=_safe_int(data.get("duplicate_active_purpose_count")),
        invalid_lifecycle_count=_safe_int(data.get("invalid_lifecycle_count")),
        incomplete_responsibility_count=_safe_int(data.get("incomplete_responsibility_count")),
    )


def _finding_to_json(finding: Finding) -> dict[str, Any]:
    return {
        "source": finding.source,
        "code": finding.code,
        "severity": finding.severity,
        "message": finding.message,
        "path": finding.path,
        "symbol": finding.symbol,
        "evidence": finding.evidence,
    }


def _finding_from_json(data: dict[str, Any]) -> Finding:
    evidence = data.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    return Finding(
        source=str(data.get("source", "verify")),
        code=str(data.get("code", "UNKNOWN")),
        severity=str(data.get("severity", "warning")),
        message=str(data.get("message", "")),
        path=str(data.get("path")) if data.get("path") is not None else None,
        symbol=str(data.get("symbol")) if data.get("symbol") is not None else None,
        evidence=evidence,
    )


def _safe_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return 0
