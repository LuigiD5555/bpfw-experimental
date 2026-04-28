"""Heuristic duplication detector comparing symbols against blueprint responsibilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bpfw.blueprint.models import BlueprintResponsibility
from bpfw.blueprint.validator import validate_blueprint
from bpfw.duplication.naming_policy import build_naming_signals, is_forbidden_duplicate
from bpfw.duplication.responsibility_matcher import best_responsibility_match
from bpfw.duplication.symbol_scanner import SymbolScanIssue, scan_project_symbols


@dataclass(slots=True)
class DuplicationFinding:
    """Potential or explicit duplication finding."""

    severity: str
    code: str
    message: str
    responsibility_id: str
    symbol_name: str
    symbol_type: str
    file_path: str
    line_number: int
    confidence: int
    recommendation: str


@dataclass(slots=True)
class DuplicationDetectionResult:
    """Detection output consumed by verify/discover."""

    findings: list[DuplicationFinding] = field(default_factory=list)
    scan_issues: list[SymbolScanIssue] = field(default_factory=list)



def _active_responsibilities(responsibilities: list[BlueprintResponsibility]) -> list[BlueprintResponsibility]:
    return [
        responsibility
        for responsibility in responsibilities
        if responsibility.lifecycle_state == "active"
    ]



def detect_duplication(project_root: Path) -> DuplicationDetectionResult:
    """Run duplication heuristics over scanned symbols and blueprint responsibilities."""

    blueprint_validation = validate_blueprint(project_root=project_root)
    if not blueprint_validation.is_valid or blueprint_validation.blueprint is None:
        first_error = blueprint_validation.errors[0]
        return DuplicationDetectionResult(
            findings=[
                DuplicationFinding(
                    severity="block",
                    code="DP100",
                    message=f"Blueprint must be valid before duplication detection: {first_error.message}",
                    responsibility_id="",
                    symbol_name="",
                    symbol_type="",
                    file_path=first_error.file_path,
                    line_number=1,
                    confidence=100,
                    recommendation=first_error.recommendation,
                )
            ]
        )

    scan_result = scan_project_symbols(project_root=project_root)
    findings: list[DuplicationFinding] = []

    active_responsibilities = _active_responsibilities(blueprint_validation.blueprint.responsibilities)
    for scanned_symbol in scan_result.symbols:
        naming_signals = build_naming_signals(scanned_symbol.symbol_name)

        blocked_by_forbidden = False
        for responsibility in active_responsibilities:
            if is_forbidden_duplicate(scanned_symbol.symbol_name, responsibility.forbidden_duplicates):
                findings.append(
                    DuplicationFinding(
                        severity="block",
                        code="DP101",
                        message=(
                            f"Forbidden duplicate symbol `{scanned_symbol.symbol_name}` "
                            f"matches forbidden_duplicates for `{responsibility.responsibility_id}`"
                        ),
                        responsibility_id=responsibility.responsibility_id,
                        symbol_name=scanned_symbol.symbol_name,
                        symbol_type=scanned_symbol.symbol_type,
                        file_path=scanned_symbol.file_path,
                        line_number=scanned_symbol.line_number,
                        confidence=100,
                        recommendation="Remove symbol or rename/re-scope it to avoid duplicated responsibility",
                    )
                )
                blocked_by_forbidden = True

        if blocked_by_forbidden:
            continue

        best_match = best_responsibility_match(
            symbol=scanned_symbol,
            symbol_tokens=naming_signals.symbol_tokens,
            responsibilities=active_responsibilities,
        )
        if best_match is None:
            continue

        overlap_text = ", ".join(best_match.token_overlap) if best_match.token_overlap else "(none)"

        should_warn = False
        warning_code = ""
        warning_message = ""
        warning_confidence = 0

        if naming_signals.has_suspicious_term and best_match.path_aligned and best_match.token_overlap:
            should_warn = True
            warning_code = "DP102"
            warning_message = (
                f"Suspicious symbol `{scanned_symbol.symbol_name}` may duplicate "
                f"`{best_match.responsibility_id}` (tokens: {overlap_text})"
            )
            warning_confidence = min(95, 60 + best_match.score * 5)
        elif len(best_match.token_overlap) >= 2 and best_match.path_aligned and best_match.score >= 6:
            should_warn = True
            warning_code = "DP103"
            warning_message = (
                f"Symbol `{scanned_symbol.symbol_name}` is highly similar to active responsibility "
                f"`{best_match.responsibility_id}` (tokens: {overlap_text})"
            )
            warning_confidence = min(90, 50 + best_match.score * 5)

        if should_warn:
            findings.append(
                DuplicationFinding(
                    severity="warning",
                    code=warning_code,
                    message=warning_message,
                    responsibility_id=best_match.responsibility_id,
                    symbol_name=scanned_symbol.symbol_name,
                    symbol_type=scanned_symbol.symbol_type,
                    file_path=scanned_symbol.file_path,
                    line_number=scanned_symbol.line_number,
                    confidence=warning_confidence,
                    recommendation="Review symbol intent and keep single responsibility implementation path",
                )
            )

    return DuplicationDetectionResult(findings=findings, scan_issues=scan_result.issues)
