"""Structural review checks for suspicious naming and drift hints."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bpfw.duplication.naming_policy import build_naming_signals, is_forbidden_duplicate
from bpfw.review.diff import FileChange


@dataclass(slots=True, frozen=True)
class StructuralFinding:
    """Finding produced by structural review checks."""

    code: str
    message: str
    file_path: str
    recommendation: str



def detect_suspicious_new_files(file_changes: list[FileChange], forbidden_duplicates: list[str]) -> list[StructuralFinding]:
    """Detect suspicious names for newly created files."""

    findings: list[StructuralFinding] = []

    for change in file_changes:
        if change.change_type != "added":
            continue

        file_stem = Path(change.path).stem
        naming_signals = build_naming_signals(file_stem)
        if is_forbidden_duplicate(file_stem, forbidden_duplicates):
            findings.append(
                StructuralFinding(
                    code="RV010",
                    message=(
                        f"New file `{change.path}` uses forbidden duplicate name `{file_stem}` for this scope"
                    ),
                    file_path=change.path,
                    recommendation="Reuse the canonical implementation or rename file to declared responsibility intent",
                )
            )
            continue

        if naming_signals.has_suspicious_term:
            suspicious_terms = ", ".join(naming_signals.suspicious_terms_found)
            findings.append(
                StructuralFinding(
                    code="RV009",
                    message=f"New file `{change.path}` has suspicious naming terms: {suspicious_terms}",
                    file_path=change.path,
                    recommendation="Use canonical naming aligned with declared responsibility intent",
                )
            )

    return findings
