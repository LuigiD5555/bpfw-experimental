"""Project scanner for optional non-Python language adapters."""

from __future__ import annotations

from pathlib import Path

from bpfw.core.catalog.models import ScanResult
from bpfw.core.source.registry import iter_source_files
from bpfw.core.source.tree_sitter_adapter import LanguageAdapterUnavailable, extract_units
from bpfw.reports.finding import (
    FINDING_SEVERITY_BLOCK,
    FINDING_SEVERITY_INFO,
    Finding,
)

_MULTILANG = frozenset({"go", "rust", "html", "css"})


def scan_non_python_project(
    project_root: Path,
    source_roots: list[str],
    ignored_paths: list[str],
) -> ScanResult:
    """Extract supported non-Python units without exposing parser-native nodes."""

    units = []
    findings: list[Finding] = []
    unavailable_reported: set[str] = set()
    for absolute_path, relative_path, definition in iter_source_files(
        project_root, source_roots, ignored_paths
    ):
        language = definition.identifier
        if language not in _MULTILANG:
            continue
        try:
            file_units, has_error = extract_units(language, absolute_path, relative_path)
        except LanguageAdapterUnavailable as error:
            if language not in unavailable_reported:
                unavailable_reported.add(language)
                findings.append(Finding(
                    source="bpfw",
                    code="LANGUAGE_ADAPTER_UNAVAILABLE",
                    severity=FINDING_SEVERITY_INFO,
                    message=str(error),
                    path=relative_path.as_posix(),
                    evidence={"language": language},
                ))
            continue
        except (OSError, UnicodeError) as error:
            findings.append(Finding(
                source="bpfw",
                code="SOURCE_READ_ERROR",
                severity=FINDING_SEVERITY_BLOCK,
                message=f"Could not read {language} source file: {error}",
                path=relative_path.as_posix(),
                evidence={"language": language},
            ))
            continue
        units.extend(file_units)
        if has_error:
            findings.append(Finding(
                source="bpfw",
                code="SOURCE_PARSE_ERROR",
                severity=FINDING_SEVERITY_BLOCK,
                message=f"BPFW found invalid or incomplete {language} syntax.",
                path=relative_path.as_posix(),
                evidence={"language": language},
            ))
    return ScanResult(
        discovered_units=sorted(units, key=lambda unit: unit.canonical_id),
        findings=findings,
    )

