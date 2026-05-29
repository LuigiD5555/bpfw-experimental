"""Persistent drift state used by the pre-inspector Drift Gate."""

import json
import os
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bpfw.core.profiling import RuntimeProfiler
from bpfw.integrations.diff.models import (
    BlueprintTarget,
    CodeTarget,
    DiffActionLevel,
    DiffItem,
    DiffItemKind,
    DiffRisk,
)
from bpfw.integrations.inspector.base import InspectIssue
from bpfw.reports.finding import Finding

_SCHEMA_VERSION = 2
_STATE_RELATIVE_PATH = Path(".bpfw") / "cache" / "drift_state.json"
_SOURCE_SUFFIXES: frozenset[str] = frozenset({".py"})
_AUTHORITY_SUFFIXES: frozenset[str] = frozenset({".yaml", ".yml", ".toml"})
_profiler = RuntimeProfiler()
_IGNORED_DIRECTORY_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
    }
)


@dataclass(slots=True)
class DriftDecisionRecord:
    """Save one human Drift Gate decision."""

    stable_id: str
    evidence_hash: str
    status: str
    decision: str
    decided_at: str
    reason: str | None = None
    issue_type: str | None = None
    block_data: dict[str, Any] | None = None
    context_lines: list[str] = field(default_factory=list)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "DriftDecisionRecord":
        """Create a record from persisted JSON data.

        Args:
            data: JSON dictionary.

        Returns:
            Drift decision record.
        """
        context_lines = data.get("context_lines")
        if not isinstance(context_lines, list):
            context_lines = []
        block_data = data.get("block_data")
        if not isinstance(block_data, dict):
            block_data = None
        return cls(
            stable_id=str(data.get("stable_id", "")),
            evidence_hash=str(data.get("evidence_hash", "")),
            status=str(data.get("status", "pending")),
            decision=str(data.get("decision", "unknown")),
            decided_at=str(data.get("decided_at", "")),
            reason=_optional_string(data.get("reason")),
            issue_type=_optional_string(data.get("issue_type")),
            block_data=block_data,
            context_lines=[str(line) for line in context_lines],
        )

    def to_json(self) -> dict[str, Any]:
        """Serialize this record to JSON-compatible data.

        Returns:
            Dictionary representation.
        """
        data: dict[str, Any] = {
            "stable_id": self.stable_id,
            "evidence_hash": self.evidence_hash,
            "status": self.status,
            "decision": self.decision,
            "decided_at": self.decided_at,
        }
        if self.reason is not None:
            data["reason"] = self.reason
        if self.issue_type is not None:
            data["issue_type"] = self.issue_type
        if self.block_data is not None:
            data["block_data"] = self.block_data
        if self.context_lines:
            data["context_lines"] = self.context_lines
        return data

    def to_inspect_issue(self) -> InspectIssue | None:
        """Restore an inspector issue from a persisted approval.

        Returns:
            Inspector issue or None when the record does not contain issue data.
        """
        if self.status != "approved_for_inspector":
            return None
        if self.issue_type is None or self.block_data is None:
            return None
        return InspectIssue(
            issue_type=self.issue_type,
            block=dict(self.block_data),
            add_on_accept=True,
            context_lines=list(self.context_lines),
        )


@dataclass(slots=True)
class DriftState:
    """Persisted drift analysis and decision state.

    Attributes:
        input_signature: Cheap project input signature used to validate the cache.
        pending_human_decisions: Number of human decisions still pending when state was saved.
        last_analyzed_at: UTC timestamp of the last analysis.
        decisions: Decisions keyed by stable drift id.
    """

    input_signature: str | None = None
    pending_human_decisions: int = 0
    last_analyzed_at: str | None = None
    decisions: dict[str, DriftDecisionRecord] = field(default_factory=dict)
    pending_items: list[DiffItem] = field(default_factory=list)
    file_fingerprints: dict[str, str] = field(default_factory=dict)
    changed_paths: list[str] = field(default_factory=list)
    added_paths: list[str] = field(default_factory=list)
    removed_paths: list[str] = field(default_factory=list)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "DriftState":
        """Create state from persisted JSON data.

        Args:
            data: JSON dictionary.

        Returns:
            Drift state.
        """
        decisions_data = data.get("decisions")
        decisions: dict[str, DriftDecisionRecord] = {}
        if isinstance(decisions_data, list):
            for record_data in decisions_data:
                if not isinstance(record_data, dict):
                    continue
                record = DriftDecisionRecord.from_json(record_data)
                if record.stable_id:
                    decisions[record.stable_id] = record
        pending_items_data = data.get("pending_items")
        pending_items: list[DiffItem] = []
        if isinstance(pending_items_data, list):
            for item_data in pending_items_data:
                if not isinstance(item_data, dict):
                    continue
                item = _diff_item_from_json(item_data)
                if item is not None:
                    pending_items.append(item)
        return cls(
            input_signature=_optional_string(data.get("input_signature")),
            pending_human_decisions=_safe_int(data.get("pending_human_decisions")),
            last_analyzed_at=_optional_string(data.get("last_analyzed_at")),
            decisions=decisions,
            pending_items=pending_items,
            file_fingerprints=_string_map(data.get("file_fingerprints")),
            changed_paths=_string_list(data.get("changed_paths")),
            added_paths=_string_list(data.get("added_paths")),
            removed_paths=_string_list(data.get("removed_paths")),
        )

    def to_json(self) -> dict[str, Any]:
        """Serialize state to JSON-compatible data.

        Returns:
            Dictionary representation.
        """
        return {
            "schema_version": _SCHEMA_VERSION,
            "input_signature": self.input_signature,
            "pending_human_decisions": self.pending_human_decisions,
            "last_analyzed_at": self.last_analyzed_at,
            "decisions": [record.to_json() for record in self.decisions.values()],
            "pending_items": [_diff_item_to_json(item) for item in self.pending_items],
            "file_fingerprints": dict(self.file_fingerprints),
            "changed_paths": list(self.changed_paths),
            "added_paths": list(self.added_paths),
            "removed_paths": list(self.removed_paths),
        }

    def record_decision(
        self,
        item: DiffItem,
        status: str,
        decision: str,
        reason: str | None = None,
        issue: InspectIssue | None = None,
    ) -> None:
        """Record one Drift Gate decision.

        Args:
            item: Diff item being decided.
            status: Decision status.
            decision: Decision label.
            reason: Optional human-readable reason.
            issue: Optional inspector issue produced by the decision.
        """
        stable_id = build_drift_stable_id(item)
        evidence_hash = build_drift_evidence_hash(item)
        context_lines: list[str] = []
        issue_type: str | None = None
        block_data: dict[str, Any] | None = None
        if issue is not None:
            context_lines = list(issue.context_lines)
            issue_type = issue.issue_type
            block_data = dict(issue.block)
        self.decisions[stable_id] = DriftDecisionRecord(
            stable_id=stable_id,
            evidence_hash=evidence_hash,
            status=status,
            decision=decision,
            decided_at=_utc_now(),
            reason=reason,
            issue_type=issue_type,
            block_data=block_data,
            context_lines=context_lines,
        )

    def current_record_for(self, item: DiffItem) -> DriftDecisionRecord | None:
        """Return a current decision record for a diff item.

        Args:
            item: Diff item to check.

        Returns:
            Matching record when stable id and evidence hash both match.
        """
        record = self.decisions.get(build_drift_stable_id(item))
        if record is None:
            return None
        if record.evidence_hash != build_drift_evidence_hash(item):
            return None
        return record

    def is_reusable_for_signature(self, input_signature: str) -> bool:
        """Return whether this state can skip a fresh drift analysis.

        Args:
            input_signature: Current project input signature.

        Returns:
            True when the signature is unchanged and no pending human decisions remain.
        """
        return self.input_signature == input_signature and self.pending_human_decisions == 0

    def has_file_fingerprints(self) -> bool:
        """Return whether this state has file-level hashes for strict delta detection."""
        return bool(self.file_fingerprints)

    def has_reusable_pending_items(self, input_signature: str) -> bool:
        """Return whether pending Drift Gate items can be restored.

        Args:
            input_signature: Current project input signature.

        Returns:
            True when pending items belong to the current unchanged input state.
        """
        return self.input_signature == input_signature and bool(self.pending_items)

    def has_pending_items(self) -> bool:
        """Return whether human Drift Gate work is waiting in the snapshot.

        Returns:
            True when at least one pending item was persisted.
        """
        return bool(self.pending_items)

    def replace_pending_items(self, pending_items: list[DiffItem]) -> None:
        """Replace persisted pending Drift Gate items.

        Args:
            pending_items: Pending human drift items to persist.
        """
        self.pending_items = list(pending_items)
        self.pending_human_decisions = len(self.pending_items)

    def restored_pending_items(self) -> list[DiffItem]:
        """Return pending Drift Gate items restored from state.

        Returns:
            Pending diff items.
        """
        return list(self.pending_items)

    def restored_inspector_issues(self) -> list[InspectIssue]:
        """Return inspector issues restored from approved pending decisions.

        Returns:
            Restored inspector issues.
        """
        issues: list[InspectIssue] = []
        for record in self.decisions.values():
            issue = record.to_inspect_issue()
            if issue is not None:
                issues.append(issue)
        return issues

    def has_approved_inspector_work(self) -> bool:
        """Return whether approved Drift Gate items still need metadata inspection.

        Returns:
            True when at least one Drift Gate decision produced an inspector issue.
        """
        return any(
            record.status == "approved_for_inspector"
            and record.issue_type is not None
            and record.block_data is not None
            for record in self.decisions.values()
        )


class DriftStateRepository:
    """Load and save persistent Drift Gate state."""

    def __init__(self, project_root: Path) -> None:
        """Initialize the repository.

        Args:
            project_root: Project root directory.
        """
        self.project_root = project_root.resolve()
        self.state_path = self.project_root / _STATE_RELATIVE_PATH

    def load(self) -> DriftState:
        """Load persisted drift state.

        Returns:
            Drift state. Missing or invalid files return empty state.
        """
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return DriftState()
        if not isinstance(data, dict):
            return DriftState()
        schema_version = data.get("schema_version")
        if schema_version not in {1, _SCHEMA_VERSION}:
            return DriftState()
        return DriftState.from_json(data)

    def save(self, state: DriftState) -> None:
        """Persist drift state.

        Args:
            state: Drift state to persist.
        """
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(state.to_json(), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def build_input_signature(self) -> str:
        """Build a cheap project input signature for drift analysis cache validation.

        Returns:
            SHA-256 digest for authority and Python source file metadata.
        """
        entries: list[dict[str, Any]] = []
        for relative_root in _signature_roots(self.project_root):
            absolute_root = self.project_root / relative_root
            if not absolute_root.exists():
                continue
            with _profiler.measure(f"drift_state.signature.walk.{relative_root.as_posix()}"):
                entries.extend(_file_metadata_entries(self.project_root, absolute_root))
        with _profiler.measure("drift_state.signature.hash"):
            payload = json.dumps(entries, sort_keys=True, separators=(",", ":"))
            return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def build_file_fingerprints(self) -> dict[str, str]:
        """Build a path -> sha256(content) map for strict drift delta detection."""
        fingerprints: dict[str, str] = {}
        for relative_root in _signature_roots(self.project_root):
            absolute_root = self.project_root / relative_root
            if not absolute_root.exists():
                continue
            with _profiler.measure(f"drift_state.fingerprints.walk.{relative_root.as_posix()}"):
                fingerprints.update(_file_hash_entries(self.project_root, absolute_root))
        return dict(sorted(fingerprints.items()))

    def detect_changes(
        self,
        previous_fingerprints: dict[str, str],
        current_fingerprints: dict[str, str],
    ) -> tuple[list[str], list[str], list[str]]:
        """Return changed, added and removed paths between fingerprint snapshots."""
        previous_paths = set(previous_fingerprints)
        current_paths = set(current_fingerprints)
        added_paths = sorted(current_paths - previous_paths)
        removed_paths = sorted(previous_paths - current_paths)
        common_paths = previous_paths & current_paths
        changed_paths = sorted(
            path for path in common_paths if previous_fingerprints.get(path) != current_fingerprints.get(path)
        )
        return changed_paths, added_paths, removed_paths


def build_drift_stable_id(item: DiffItem) -> str:
    """Build a stable identifier for one drift item.

    Args:
        item: Diff item.

    Returns:
        Stable string identifier.
    """
    parts = [item.kind.value]
    if item.blueprint_target is not None:
        parts.extend(
            [
                item.blueprint_target.block_id or "",
                item.blueprint_target.path or "",
                item.blueprint_target.symbol or "",
                item.blueprint_target.kind or "",
            ]
        )
    if item.code_target is not None:
        parts.extend([item.code_target.path, item.code_target.symbol, item.code_target.kind])
    if item.finding is not None:
        purpose = item.finding.evidence.get("purpose") if isinstance(item.finding.evidence, dict) else None
        if purpose is not None:
            parts.append(str(purpose))
    if item.related_blocks:
        parts.extend(sorted(block.block_id for block in item.related_blocks if block.block_id))
    return ":".join(_normalize_part(part) for part in parts if part is not None)


def build_drift_evidence_hash(item: DiffItem) -> str:
    """Build an evidence hash for one drift item.

    Args:
        item: Diff item.

    Returns:
        SHA-256 hash of evidence that invalidates stale decisions when changed.
    """
    payload = {
        "kind": item.kind.value,
        "risk": item.risk.value,
        "reason": item.reason,
        "finding": _finding_payload(item),
        "code_target": _code_target_payload(item),
        "blueprint_target": _blueprint_target_payload(item),
        "candidates": [
            {
                "path": candidate.path,
                "symbol": candidate.symbol,
                "kind": candidate.kind,
                "qualified_name": candidate.qualified_name,
            }
            for candidate in item.candidates
        ],
        "related_blocks": [
            {
                "block_id": block.block_id,
                "path": block.path,
                "symbol": block.symbol,
                "kind": block.kind,
                "purpose": block.purpose,
                "status": block.status,
            }
            for block in item.related_blocks
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _file_metadata_entries(project_root: Path, root: Path) -> list[dict[str, Any]]:
    """Build file metadata entries under a root directory.

    Args:
        project_root: Project root directory.
        root: Directory to walk.

    Returns:
        Sorted metadata entries.
    """
    entries: list[dict[str, Any]] = []
    ignored_directories = set(_IGNORED_DIRECTORY_NAMES) | {".locks"}
    for current_root, directory_names, file_names in os.walk(root):
        directory_names[:] = [name for name in directory_names if name not in ignored_directories]
        for file_name in file_names:
            path = Path(current_root) / file_name
            if _should_ignore_path(path):
                continue
            if not _is_relevant_file(path):
                continue
            try:
                stat_result = path.stat()
            except OSError:
                continue
            entries.append(
                {
                    "path": path.relative_to(project_root).as_posix(),
                    "size": stat_result.st_size,
                    "mtime_ns": stat_result.st_mtime_ns,
                }
            )
    entries.sort(key=lambda entry: entry["path"])
    return entries


def _file_hash_entries(project_root: Path, root: Path) -> dict[str, str]:
    """Build content hash entries under a root directory."""
    entries: dict[str, str] = {}
    ignored_directories = set(_IGNORED_DIRECTORY_NAMES) | {".locks", "cache"}
    for current_root, directory_names, file_names in os.walk(root):
        directory_names[:] = [name for name in directory_names if name not in ignored_directories]
        for file_name in file_names:
            path = Path(current_root) / file_name
            if _should_ignore_path(path):
                continue
            if not _is_relevant_file(path):
                continue
            relative_path = path.relative_to(project_root).as_posix()
            digest = _hash_file_contents(path)
            if digest is None:
                continue
            entries[relative_path] = digest
    return entries


def _hash_file_contents(path: Path) -> str | None:
    """Hash file contents using sha256."""
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as file_handle:
            for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
                hasher.update(chunk)
    except OSError:
        return None
    return hasher.hexdigest()


def _should_ignore_path(path: Path) -> bool:
    """Return whether a path should be ignored by the drift input signature.

    Args:
        path: File path.

    Returns:
        True when the path is cache, lock, or generated noise.
    """
    parts = set(path.parts)
    if parts & _IGNORED_DIRECTORY_NAMES:
        return True
    return path.name == "drift_state.json" or ".locks" in parts


def _is_relevant_file(path: Path) -> bool:
    """Return whether a file affects drift analysis.

    Args:
        path: File path.

    Returns:
        True for Python source and authority/config files.
    """
    if path.suffix in _SOURCE_SUFFIXES:
        return True
    if path.suffix in _AUTHORITY_SUFFIXES and "bpfw" in path.parts:
        return True
    return False


def _signature_roots(project_root: Path) -> tuple[Path, ...]:
    """Return deterministic roots used by drift signatures and fingerprints."""
    roots: list[Path] = []
    source_roots = _load_source_roots(project_root)
    for source_root in source_roots:
        roots.append(Path(source_root))
    if (project_root / "bpfw").exists():
        roots.append(Path("bpfw"))
    # preserve stable order and remove duplicates
    ordered: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = root.as_posix()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(root)
    return tuple(ordered)


def _load_source_roots(project_root: Path) -> tuple[str, ...]:
    """Read source roots from blueprint config, fallback to src."""
    default_roots = ("src",)
    blueprint_path = project_root / "bpfw" / "blueprint.yaml"
    if not blueprint_path.exists():
        return default_roots
    try:
        import yaml
    except Exception:
        return default_roots
    try:
        payload = yaml.safe_load(blueprint_path.read_text(encoding="utf-8"))
    except Exception:
        return default_roots
    if not isinstance(payload, dict):
        return default_roots
    raw_roots = payload.get("source_roots")
    if not isinstance(raw_roots, list):
        return default_roots
    cleaned_roots = [str(item).strip() for item in raw_roots if str(item).strip()]
    if not cleaned_roots:
        return default_roots
    return tuple(cleaned_roots)


def _finding_payload(item: DiffItem) -> dict[str, Any] | None:
    """Build a serializable finding data."""
    finding = item.finding
    if finding is None:
        return None
    return {
        "code": finding.code,
        "path": finding.path,
        "symbol": finding.symbol,
        "message": finding.message,
        "evidence": finding.evidence,
    }


def _code_target_payload(item: DiffItem) -> dict[str, Any] | None:
    """Build a serializable code target data."""
    target = item.code_target
    if target is None:
        return None
    return {
        "path": target.path,
        "symbol": target.symbol,
        "kind": target.kind,
        "qualified_name": target.qualified_name,
        "start_line": target.start_line,
        "end_line": target.end_line,
    }


def _blueprint_target_payload(item: DiffItem) -> dict[str, Any] | None:
    """Build a serializable blueprint target data."""
    target = item.blueprint_target
    if target is None:
        return None
    detected = target.block_data.get("detected") if isinstance(target.block_data, dict) else None
    return {
        "block_id": target.block_id,
        "path": target.path,
        "symbol": target.symbol,
        "kind": target.kind,
        "source_shard_path": target.source_shard_path.as_posix() if target.source_shard_path else None,
        "purpose": target.purpose,
        "name": target.name,
        "domain": target.domain,
        "status": target.status,
        "detected": detected if isinstance(detected, dict) else None,
        "block_data": target.block_data if isinstance(target.block_data, dict) else {},
    }


def _normalize_part(value: str) -> str:
    """Normalize one stable id segment.

    Args:
        value: Segment value.

    Returns:
        Normalized segment.
    """
    return value.strip().replace("\n", " ").replace(":", "_")


def _optional_string(value: Any) -> str | None:
    """Return a non-empty string or None.

    Args:
        value: Candidate value.

    Returns:
        Stripped string or None.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_map(value: Any) -> dict[str, str]:
    """Return a safe string map."""
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, item in value.items():
        key_text = _optional_string(key)
        value_text = _optional_string(item)
        if key_text is None or value_text is None:
            continue
        result[key_text] = value_text
    return result


def _string_list(value: Any) -> list[str]:
    """Return a safe string list."""
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _optional_string(item)
        if text is not None:
            result.append(text)
    return result


def _safe_int(value: Any) -> int:
    """Return a safe non-negative integer.

    Args:
        value: Candidate value.

    Returns:
        Integer value or zero.
    """
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def _utc_now() -> str:
    """Return a compact UTC timestamp.

    Returns:
        ISO-8601 timestamp.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _diff_item_to_json(item: DiffItem) -> dict[str, Any]:
    """Convert a diff item to saved JSON data."""
    return {
        "identifier": item.identifier,
        "kind": item.kind.value,
        "action_level": item.action_level.value,
        "risk": item.risk.value,
        "reason": item.reason,
        "finding": _finding_payload(item),
        "code_target": _code_target_payload(item),
        "blueprint_target": _blueprint_target_payload(item),
        "candidates": [_code_target_to_json(candidate) for candidate in item.candidates],
        "related_blocks": [_blueprint_target_to_json(block) for block in item.related_blocks],
    }


def _diff_item_from_json(data: dict[str, Any]) -> DiffItem | None:
    """Deconvert a diff item from data saved as JSON."""
    try:
        kind = DiffItemKind(str(data.get("kind")))
        action_level = DiffActionLevel(str(data.get("action_level")))
        risk = DiffRisk(str(data.get("risk")))
    except ValueError:
        return None
    finding = _finding_from_json(data.get("finding"))
    code_target = _code_target_from_json(data.get("code_target"))
    blueprint_target = _blueprint_target_from_json(data.get("blueprint_target"))
    candidates_data = data.get("candidates")
    candidates: list[CodeTarget] = []
    if isinstance(candidates_data, list):
        for candidate_data in candidates_data:
            candidate = _code_target_from_json(candidate_data)
            if candidate is not None:
                candidates.append(candidate)
    related_data = data.get("related_blocks")
    related_blocks: list[BlueprintTarget] = []
    if isinstance(related_data, list):
        for block_data in related_data:
            block = _blueprint_target_from_json(block_data)
            if block is not None:
                related_blocks.append(block)
    return DiffItem(
        identifier=str(data.get("identifier", "cached-drift-item")),
        kind=kind,
        action_level=action_level,
        risk=risk,
        reason=str(data.get("reason", "Cached drift item.")),
        finding=finding,
        code_target=code_target,
        blueprint_target=blueprint_target,
        candidates=tuple(candidates),
        related_blocks=tuple(related_blocks),
    )


def _finding_from_json(data: Any) -> Finding | None:
    """Deconvert a finding from JSON data."""
    if not isinstance(data, dict):
        return None
    evidence = data.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    return Finding(
        source=str(data.get("source", "bpfw")),
        code=str(data.get("code", "UNKNOWN")),
        severity=str(data.get("severity", "warning")),
        message=str(data.get("message", "Cached finding.")),
        path=_optional_string(data.get("path")),
        symbol=_optional_string(data.get("symbol")),
        evidence=evidence,
    )


def _code_target_from_json(data: Any) -> CodeTarget | None:
    """Deconvert a code target from JSON data."""
    if not isinstance(data, dict):
        return None
    path = _optional_string(data.get("path"))
    symbol = _optional_string(data.get("symbol"))
    kind = _optional_string(data.get("kind"))
    if path is None or symbol is None or kind is None:
        return None
    return CodeTarget(
        path=path,
        symbol=symbol,
        kind=kind,
        start_line=_optional_int(data.get("start_line")),
        end_line=_optional_int(data.get("end_line")),
        qualified_name=_optional_string(data.get("qualified_name")),
    )


def _blueprint_target_from_json(data: Any) -> BlueprintTarget | None:
    """Deconvert a blueprint target from JSON data."""
    if not isinstance(data, dict):
        return None
    block_id = _optional_string(data.get("block_id"))
    if block_id is None:
        return None
    source_shard = _optional_string(data.get("source_shard_path"))
    block_data = data.get("block_data")
    if not isinstance(block_data, dict):
        block_data = {}
    return BlueprintTarget(
        block_id=block_id,
        path=_optional_string(data.get("path")),
        symbol=_optional_string(data.get("symbol")),
        kind=_optional_string(data.get("kind")),
        source_shard_path=Path(source_shard) if source_shard else None,
        purpose=_optional_string(data.get("purpose")),
        name=_optional_string(data.get("name")),
        domain=_optional_string(data.get("domain")),
        status=_optional_string(data.get("status")),
        block_data=block_data,
    )


def _code_target_to_json(target: CodeTarget) -> dict[str, Any]:
    """Serialize a code target.

    Args:
        target: Code target.

    Returns:
        JSON-compatible dictionary.
    """
    return {
        "path": target.path,
        "symbol": target.symbol,
        "kind": target.kind,
        "start_line": target.start_line,
        "end_line": target.end_line,
        "qualified_name": target.qualified_name,
    }


def _blueprint_target_to_json(target: BlueprintTarget) -> dict[str, Any]:
    """Serialize a blueprint target.

    Args:
        target: Blueprint target.

    Returns:
        JSON-compatible dictionary.
    """
    return {
        "block_id": target.block_id,
        "path": target.path,
        "symbol": target.symbol,
        "kind": target.kind,
        "source_shard_path": target.source_shard_path.as_posix() if target.source_shard_path else None,
        "purpose": target.purpose,
        "name": target.name,
        "domain": target.domain,
        "status": target.status,
        "block_data": target.block_data,
    }


def _optional_int(value: Any) -> int | None:
    """Return an optional integer.

    Args:
        value: Candidate value.

    Returns:
        Integer or None.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
