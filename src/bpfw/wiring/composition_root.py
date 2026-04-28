"""Wiring source validation against authorized composition roots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bpfw.composition.root import CompositionRootError, is_authorized_composition_file, resolve_composition_roots


@dataclass(slots=True)
class WiringSourceCheckResult:
    """Result for runtime binding source authorization."""

    is_authorized: bool
    resolved_source: str
    message: str = ""



def _extract_source_path(raw_source: str) -> str:
    stripped_source = raw_source.strip()
    if not stripped_source:
        return ""

    # Marker mode can include file:line evidence. Strip line number suffix.
    path_text, separator, line_text = stripped_source.rpartition(":")
    if separator and line_text.isdigit() and path_text:
        return path_text
    return stripped_source



def validate_runtime_source(project_root: Path, source: str) -> WiringSourceCheckResult:
    """Validate that runtime source file is an authorized composition root location."""

    source_path_text = _extract_source_path(source)
    if not source_path_text:
        return WiringSourceCheckResult(
            is_authorized=False,
            resolved_source="",
            message="Runtime binding source is empty",
        )

    if source_path_text.startswith(".bpfw/"):
        # Metadata source is accepted in phase-6 baseline.
        return WiringSourceCheckResult(is_authorized=True, resolved_source=source_path_text)

    source_candidate = Path(source_path_text)
    if not source_candidate.is_absolute():
        source_candidate = project_root / source_candidate
    resolved_candidate = source_candidate.resolve()

    try:
        composition_roots = resolve_composition_roots(project_root=project_root)
    except CompositionRootError as error:
        return WiringSourceCheckResult(
            is_authorized=False,
            resolved_source=str(resolved_candidate),
            message=f"Cannot resolve composition roots: {error}",
        )

    is_authorized = is_authorized_composition_file(
        file_path=resolved_candidate,
        composition_roots=composition_roots,
    )
    if is_authorized:
        return WiringSourceCheckResult(is_authorized=True, resolved_source=str(resolved_candidate))

    return WiringSourceCheckResult(
        is_authorized=False,
        resolved_source=str(resolved_candidate),
        message="Runtime source is outside authorized composition roots",
    )
