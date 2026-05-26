"""Persistent inspector editing state for resume-on-reopen."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bpfw.integrations.inspector.base import InspectIssue

_STATE_PATH = Path('.bpfw') / 'cache' / 'inspector_state.json'
_SCHEMA_VERSION = 1


@dataclass(slots=True)
class InspectorResumeState:
    """Persisted inspector editing state for one interactive session."""

    input_signature: str
    current_index: int
    mode_name: str
    issues: list[InspectIssue]
    saved_at: str

    def to_json(self) -> dict[str, Any]:
        return {
            'schema_version': _SCHEMA_VERSION,
            'input_signature': self.input_signature,
            'current_index': self.current_index,
            'mode_name': self.mode_name,
            'saved_at': self.saved_at,
            'issues': [
                {
                    'issue_type': issue.issue_type,
                    'block': issue.block,
                    'add_on_accept': issue.add_on_accept,
                    'context_lines': list(issue.context_lines),
                }
                for issue in self.issues
            ],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> InspectorResumeState | None:
        if not isinstance(data, dict):
            return None
        if data.get('schema_version') != _SCHEMA_VERSION:
            return None
        input_signature = str(data.get('input_signature') or '').strip()
        if not input_signature:
            return None
        current_index_value = data.get('current_index')
        current_index = int(current_index_value) if isinstance(current_index_value, int) else 0
        mode_name = str(data.get('mode_name') or 'compact').strip() or 'compact'
        saved_at = str(data.get('saved_at') or '').strip()

        issues_payload = data.get('issues')
        issues: list[InspectIssue] = []
        if isinstance(issues_payload, list):
            for item in issues_payload:
                if not isinstance(item, dict):
                    continue
                issue_type = str(item.get('issue_type') or '').strip()
                block = item.get('block')
                if not issue_type or not isinstance(block, dict):
                    continue
                add_on_accept = bool(item.get('add_on_accept', False))
                context_lines_value = item.get('context_lines')
                context_lines: list[str] = []
                if isinstance(context_lines_value, list):
                    context_lines = [str(line) for line in context_lines_value]
                issues.append(
                    InspectIssue(
                        issue_type=issue_type,
                        block=block,
                        add_on_accept=add_on_accept,
                        context_lines=context_lines,
                    )
                )
        return cls(
            input_signature=input_signature,
            current_index=max(0, current_index),
            mode_name=mode_name,
            issues=issues,
            saved_at=saved_at,
        )


class InspectorStateRepository:
    """Load/save inspector resume snapshots."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.path = self.project_root / _STATE_PATH

    def load(self) -> InspectorResumeState | None:
        try:
            payload = json.loads(self.path.read_text(encoding='utf-8'))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        return InspectorResumeState.from_json(payload)

    def save(self, state: InspectorResumeState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state.to_json(), indent=2, sort_keys=True), encoding='utf-8')

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            return


def now_iso_utc() -> str:
    """Return current UTC time in ISO-8601 format without microseconds."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
