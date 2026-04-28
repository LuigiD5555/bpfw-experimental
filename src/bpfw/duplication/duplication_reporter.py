"""Reporting helpers for duplication detection output."""

from __future__ import annotations

from bpfw.duplication.similarity_detector import DuplicationDetectionResult, DuplicationFinding



def _severity_rank(severity: str) -> int:
    ranking = {
        "critical": 4,
        "block": 3,
        "warning": 2,
        "info": 1,
        "ok": 0,
    }
    return ranking.get(severity, 0)



def sort_findings(findings: list[DuplicationFinding]) -> list[DuplicationFinding]:
    return sorted(
        findings,
        key=lambda finding: (_severity_rank(finding.severity), finding.confidence),
        reverse=True,
    )



def primary_finding(result: DuplicationDetectionResult) -> DuplicationFinding | None:
    if not result.findings:
        return None
    return sort_findings(result.findings)[0]



def summarize_counts(result: DuplicationDetectionResult) -> dict[str, str]:
    warning_count = sum(1 for finding in result.findings if finding.severity == "warning")
    block_count = sum(1 for finding in result.findings if finding.severity == "block")
    critical_count = sum(1 for finding in result.findings if finding.severity == "critical")
    return {
        "duplication_warning_count": str(warning_count),
        "duplication_block_count": str(block_count),
        "duplication_critical_count": str(critical_count),
        "duplication_total_count": str(len(result.findings)),
        "duplication_scan_issue_count": str(len(result.scan_issues)),
    }



def findings_to_human_lines(result: DuplicationDetectionResult, limit: int = 5) -> str:
    if not result.findings:
        return "(no duplication findings)"

    lines: list[str] = []
    for finding in sort_findings(result.findings)[:limit]:
        lines.append(
            (
                f"- [{finding.severity.upper()}] {finding.code} {finding.symbol_name} "
                f"-> {finding.responsibility_id} ({finding.file_path}:{finding.line_number})"
            )
        )
    return "\n".join(lines)
