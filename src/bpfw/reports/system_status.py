"""Compact Blueprint v2 intent/system status rendering."""
from __future__ import annotations
from bpfw.core.catalog.models import VerificationReport


def render_system_status(report: VerificationReport) -> str:
    findings = report.findings
    def has_prefix(codes: set[str]) -> bool:
        return any(f.code in codes and f.severity == "block" for f in findings)
    structure = "DRIFT" if has_prefix({"MISSING_DECLARED_CODE", "UNDECLARED_CODE", "INCOMPLETE_BLOCK"}) else "ALIGNED"
    intent = "DRIFT" if has_prefix({"INTENT_DRIFT"}) else "PRESERVED"
    logic = "VIOLATION" if any(f.category in {"logical_drift", "interaction_drift"} and f.severity == "block" for f in findings) else "ALIGNED"
    interactions = sum(1 for f in findings if f.category == "interaction_drift")
    evidence_fail = any(f.code in {"DYNAMIC_EVIDENCE_FAILED", "PIPECRAFT_VALIDATION_FAILED", "PIPECRAFT_PLAN_FAILED"} for f in findings)
    evidence_missing = any(f.code == "EVIDENCE_MISSING" for f in findings)
    evidence_stale = any(f.code == "EVIDENCE_STALE" for f in findings)
    evidence_seen = any(f.source == "evidence" for f in findings)
    behavior = "FAILED" if evidence_fail else "STALE" if evidence_stale else "UNVERIFIED" if evidence_missing else "CHECKED" if evidence_seen else "STATIC"
    evidence_status = "FAILED" if evidence_fail else "STALE" if evidence_stale else "MISSING" if evidence_missing else "CURRENT" if evidence_seen else "NOT REQUIRED"
    return "\n".join([
        "BPFW SYSTEM STATUS",
        "────────────────────────────",
        f"Structure       {structure}",
        f"Intent          {intent}",
        f"Logic           {logic}",
        f"Behavior        {behavior}",
        f"Interactions    {interactions} finding(s)",
        f"Evidence        {evidence_status}",
    ])
