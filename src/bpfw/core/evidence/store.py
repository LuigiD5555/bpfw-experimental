"""Local evidence persistence under .bpfw/cache with corruption-aware reads."""
from __future__ import annotations

import json
from pathlib import Path

from bpfw.core.atomic_io import append_jsonl_durable
from bpfw.core.evidence.models import EvidenceRecord


class EvidenceStoreCorruption(RuntimeError):
    """Raised when journal corruption could hide a newer evidence record."""

    def __init__(self, path: Path, line_number: int) -> None:
        self.path = path
        self.line_number = line_number
        super().__init__(f"evidence journal is corrupt at {path}:{line_number}")


class EvidenceStore:
    def __init__(self, project_root: Path) -> None:
        self.path = project_root / ".bpfw" / "cache" / "evidence.jsonl"

    def append(self, record: EvidenceRecord) -> None:
        append_jsonl_durable(self.path, record.to_dict())

    def latest(self, invariant_id: str) -> EvidenceRecord | None:
        if not self.path.exists():
            return None

        selected: dict | None = None
        selected_line = 0
        last_corrupt_line = 0
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise EvidenceStoreCorruption(self.path, 0) from error

        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                last_corrupt_line = line_number
                continue
            if not isinstance(item, dict):
                last_corrupt_line = line_number
                continue
            if item.get("invariant_id") == invariant_id:
                selected = item
                selected_line = line_number

        # A corrupt record after the latest known matching record might itself
        # be a newer record for this invariant.  Treating the older PASS as
        # current would therefore be unsafe.  A later valid record supersedes
        # earlier corruption and can be trusted again.
        if last_corrupt_line and selected_line <= last_corrupt_line:
            raise EvidenceStoreCorruption(self.path, last_corrupt_line)

        if selected is None:
            return None
        try:
            return EvidenceRecord(**selected)
        except (TypeError, ValueError) as error:
            raise EvidenceStoreCorruption(self.path, selected_line) from error

    def is_current(self, invariant_id: str, fingerprint: str) -> bool:
        try:
            latest = self.latest(invariant_id)
        except EvidenceStoreCorruption:
            return False
        return latest is not None and latest.status == "pass" and latest.fingerprint == fingerprint
