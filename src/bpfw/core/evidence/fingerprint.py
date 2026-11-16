"""Stable evidence fingerprinting for project inputs and verification configuration."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from bpfw.core.catalog.domain.models import BlueprintDocument


def fingerprint_paths(project_root: Path, paths: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for value in sorted(set(paths)):
        relative = Path(value)
        absolute = project_root / relative
        digest.update(relative.as_posix().encode("utf-8"))
        if not absolute.exists() or not absolute.is_file():
            digest.update(b"<missing>")
            continue
        try:
            digest.update(absolute.read_bytes())
        except OSError:
            digest.update(b"<unreadable>")
    return digest.hexdigest()


def _semantic_sort(values: list[Any]) -> list[Any]:
    return sorted(values, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def _evidence_configuration(document: BlueprintDocument) -> dict[str, Any]:
    """Return verification semantics that must invalidate previously stored evidence."""
    blocks: list[dict[str, Any]] = []
    for block in sorted(document.blocks, key=lambda item: item.identifier):
        protected = [
            invariant.model_dump(by_alias=True, exclude_none=True)
            for invariant in block.invariants
            if invariant.evidence
        ]
        if not protected:
            continue
        blocks.append({
            "id": block.identifier,
            "invariants": _semantic_sort(protected),
        })
    scenarios = document.model_extra.get("scenarios", []) if document.model_extra else []
    if isinstance(scenarios, list):
        scenarios = _semantic_sort(scenarios)
    return {"blocks": blocks, "scenarios": scenarios}


def fingerprint_evidence(document: BlueprintDocument, project_root: Path) -> str:
    """Fingerprint executable evidence plus all artifact bytes it is intended to validate."""
    artifact_paths = [
        artifact.path
        for block in document.blocks
        for artifact in block.all_artifacts()
        if artifact.path
    ]
    digest = hashlib.sha256()
    digest.update(fingerprint_paths(project_root, artifact_paths).encode("ascii"))
    payload = _evidence_configuration(document)
    digest.update(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return digest.hexdigest()
