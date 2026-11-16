"""Persistent intent fingerprints and explicit intent-change acceptance."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bpfw.core.catalog.domain.models import BlueprintDocument
from bpfw.core.atomic_io import append_jsonl_durable, atomic_write_text
from bpfw.reports.finding import Finding

STATE_FILE = Path(".bpfw/history/intent-state.json")
LEDGER_FILE = Path(".bpfw/history/intent-changes.jsonl")


class IntentStateError(RuntimeError):
    """Raised when persisted intent continuity state cannot be trusted."""


def _sort_semantic_items(values: list[Any]) -> list[Any]:
    """Sort unordered semantic collections without rewriting nested meaning."""
    return sorted(values, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def _canonical_intent(intent: Any) -> dict[str, Any] | None:
    if intent is None:
        return None
    payload = intent.model_dump(exclude_none=True)
    for key in ("guarantees", "assumptions", "constraints"):
        value = payload.get(key)
        if isinstance(value, list):
            payload[key] = _sort_semantic_items(value)
    return payload


def _canonical_invariants(values: list[Any]) -> list[dict[str, Any]]:
    payloads = [item.model_dump(by_alias=True, exclude_none=True) for item in values]
    return _sort_semantic_items(payloads)


def _canonical_intent_payload(document: BlueprintDocument) -> dict[str, Any]:
    blocks: dict[str, Any] = {}
    for block in sorted(document.blocks, key=lambda item: item.identifier):
        if block.intent is None and not block.invariants:
            continue
        blocks[block.identifier] = {
            "purpose": block.purpose,
            "intent": _canonical_intent(block.intent),
            "invariants": _canonical_invariants(block.invariants),
        }
    project_invariants = document.model_extra.get("invariants", []) if document.model_extra else []
    if isinstance(project_invariants, list):
        project_invariants = _sort_semantic_items(project_invariants)
    return {"blocks": blocks, "invariants": project_invariants}


def intent_fingerprint(document: BlueprintDocument) -> str:
    payload = _canonical_intent_payload(document)
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(slots=True)
class IntentContinuityManager:
    project_root: Path

    @property
    def state_path(self) -> Path:
        return self.project_root / STATE_FILE

    @property
    def ledger_path(self) -> Path:
        return self.project_root / LEDGER_FILE

    def _read_state(self) -> dict[str, Any] | None:
        if not self.state_path.exists():
            return None
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except OSError as error:
            raise IntentStateError(f"cannot read intent state: {error}") from error
        except json.JSONDecodeError as error:
            raise IntentStateError(
                f"intent state is invalid JSON at line {error.lineno}, column {error.colno}"
            ) from error
        if not isinstance(value, dict):
            raise IntentStateError("intent state must be a JSON object")
        fingerprint = value.get("fingerprint")
        if not isinstance(fingerprint, str) or len(fingerprint) != 64:
            raise IntentStateError("intent state fingerprint is missing or invalid")
        try:
            int(fingerprint, 16)
        except ValueError as error:
            raise IntentStateError("intent state fingerprint is not hexadecimal") from error
        return value

    def _write_state(self, fingerprint: str, snapshot: dict[str, Any] | None = None) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fingerprint": fingerprint,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        if snapshot is not None:
            payload["snapshot"] = snapshot
        atomic_write_text(
            self.state_path,
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def ensure_baseline(self, document: BlueprintDocument) -> None:
        if (document.version or 1) < 2:
            return
        if self._read_state() is None:
            self._write_state(intent_fingerprint(document), _canonical_intent_payload(document))

    def check(self, document: BlueprintDocument) -> list[Finding]:
        if (document.version or 1) < 2:
            return []
        current = intent_fingerprint(document)
        try:
            state = self._read_state()
        except IntentStateError as error:
            return [Finding(
                source="intent_continuity",
                code="INTENT_STATE_CORRUPT",
                severity="block",
                message="Stored intent continuity state cannot be trusted; refusing to establish a new baseline implicitly.",
                evidence={
                    "state_path": str(self.state_path),
                    "reason": str(error),
                    "recovery_command": "bpfw intent accept --reason <reason>",
                },
                category="intent_drift",
                confidence="high",
            )]
        if state is None:
            self._write_state(current, _canonical_intent_payload(document))
            return []
        previous = state.get("fingerprint")
        if previous == current:
            return []
        return [Finding(
            source="intent_continuity",
            code="INTENT_DRIFT",
            severity="block",
            message="Blueprint intent or protected invariants changed without an explicit intent acceptance.",
            evidence={"previous_fingerprint": previous, "current_fingerprint": current,
                      "accept_command": "bpfw intent accept --reason <reason>"},
            category="intent_drift",
            confidence="high",
        )]

    def accept(self, document: BlueprintDocument, *, reason: str) -> dict[str, Any]:
        clean_reason = reason.strip()
        if not clean_reason:
            raise ValueError("A non-empty reason is required to accept an intent change.")
        current = intent_fingerprint(document)
        recovered_corrupt_state = False
        try:
            previous_state = self._read_state() or {}
        except IntentStateError:
            # Explicit acceptance is the recovery boundary.  A user has chosen
            # to establish the current intent as authoritative, so it is safe to
            # replace corrupt state while preserving that fact in the ledger.
            previous_state = {}
            recovered_corrupt_state = True
        previous = previous_state.get("fingerprint")
        previous_snapshot = previous_state.get("snapshot") if isinstance(previous_state.get("snapshot"), dict) else {}
        current_snapshot = _canonical_intent_payload(document)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "previous_fingerprint": previous,
            "new_fingerprint": current,
            "reason": clean_reason,
            "recovered_corrupt_state": recovered_corrupt_state,
        }
        append_jsonl_durable(self.ledger_path, entry)
        self._write_state(current, current_snapshot)
        try:
            from bpfw.core.history.ledger import HistoryLedger
            rich_ledger = HistoryLedger(self.project_root)
            rich_ledger.append({
                "event_type": "INTENT_ACCEPTED",
                "entity": {"type": "blueprint", "id_at_event": "project_intent"},
                "change": {"previous_fingerprint": previous, "new_fingerprint": current},
                "reason": {"summary": clean_reason},
                "provenance": {"trigger": "bpfw intent accept", "legacy_ledger": str(self.ledger_path)},
                "decision": {"status": "accepted"},
            })
            previous_blocks = previous_snapshot.get("blocks", {}) if isinstance(previous_snapshot.get("blocks"), dict) else {}
            current_blocks = current_snapshot.get("blocks", {}) if isinstance(current_snapshot.get("blocks"), dict) else {}
            for block_id in sorted(set(previous_blocks) | set(current_blocks)):
                if previous_blocks.get(block_id) == current_blocks.get(block_id):
                    continue
                rich_ledger.append({
                    "event_type": "INTENT_ACCEPTED",
                    "entity": {"type": "blueprint_block", "id_at_event": block_id},
                    "change": {
                        "before": rich_ledger.store_object(previous_blocks.get(block_id)) if block_id in previous_blocks else None,
                        "after": rich_ledger.store_object(current_blocks.get(block_id)) if block_id in current_blocks else None,
                    },
                    "reason": {"summary": clean_reason},
                    "provenance": {"trigger": "bpfw intent accept"},
                    "decision": {"status": "accepted"},
                })
        except Exception:
            # Legacy intent continuity remains authoritative even if rich history indexing fails.
            pass
        return entry
