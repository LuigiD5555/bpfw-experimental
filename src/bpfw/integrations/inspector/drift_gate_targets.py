"""Authority target resolution and Inspector issue construction for Drift Gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bpfw.core.catalog.models import DiscoveredCodeUnit
from bpfw.integrations.diff.models import BlueprintTarget, CodeTarget, DiffItem
from bpfw.integrations.diff.review import DiffReviewSnapshot
from bpfw.integrations.inspector.base import (
    InspectIssue,
    build_new_detected_responsibility,
    clean_string,
)
from bpfw.integrations.inspector.drift_gate_helpers import block_from_code_target


class DriftTargetResolver:
    """Resolve current authority targets independently from interactive review."""

    def __init__(self, project_root: Path, authority_document: Any | None = None) -> None:
        self.project_root = Path(project_root)
        self.authority_document = authority_document
        self.cache: dict[str, BlueprintTarget] | None = None

    def hydrate(self, target: BlueprintTarget | None) -> BlueprintTarget | None:
        if target is None:
            return None
        if target.source_shard_path is not None and target.block_data:
            return target
        current = self.by_id(target.block_id)
        if current is None:
            return target
        return BlueprintTarget(
            block_id=target.block_id,
            path=target.path or current.path,
            symbol=target.symbol or current.symbol,
            kind=target.kind or current.kind,
            source_shard_path=target.source_shard_path or current.source_shard_path,
            purpose=target.purpose or current.purpose,
            name=target.name or current.name,
            domain=target.domain or current.domain,
            status=target.status or current.status,
            block_data=target.block_data or current.block_data,
        )

    def by_id(self, block_id: str) -> BlueprintTarget | None:
        if self.cache is None:
            self.cache = self.build_cache()
        return self.cache.get(block_id)

    def build_cache(self) -> dict[str, BlueprintTarget]:
        if self.authority_document is not None:
            return self.targets_from_document(self.authority_document)
        try:
            from bpfw.core.authority import AuthorityIndex, AuthorityShard
            from bpfw.core.authority.errors import AuthorityError

            index = AuthorityIndex.load(self.project_root)
            targets: dict[str, BlueprintTarget] = {}
            for shard_path in index.get_includes():
                shard = AuthorityShard.load(self.project_root, shard_path)
                for block in shard.get_blocks():
                    target = self.target_from_block(block=block, shard_path=shard_path)
                    if target is not None:
                        targets[target.block_id] = target
            return targets
        except (AuthorityError, FileNotFoundError, OSError, ValueError):
            return {}

    def targets_from_document(self, document: Any) -> dict[str, BlueprintTarget]:
        targets: dict[str, BlueprintTarget] = {}
        for block in document.get_blocks():
            if not isinstance(block, dict):
                continue
            block_id = block.get("id")
            if not isinstance(block_id, str) or not block_id.strip():
                continue
            target = self.target_from_block(block=block, shard_path=document.block_origins.get(block_id))
            if target is not None:
                targets[target.block_id] = target
        return targets

    @staticmethod
    def target_from_block(block: dict[str, Any], shard_path: Path | None) -> BlueprintTarget | None:
        block_id = block.get("id")
        if not isinstance(block_id, str) or not block_id.strip():
            return None
        code = block.get("code")
        if not isinstance(code, dict):
            code = {}
        return BlueprintTarget(
            block_id=block_id,
            path=clean_string(code.get("path")),
            symbol=clean_string(code.get("symbol")),
            kind=clean_string(code.get("kind")),
            source_shard_path=shard_path,
            purpose=clean_string(block.get("purpose")),
            name=clean_string(block.get("name")),
            domain=clean_string(block.get("domain")),
            status=clean_string(block.get("status") or block.get("lifecycle")),
            block_data=dict(block),
        )

    def find_for_code(self, candidate: CodeTarget, exclude_block_id: str | None = None) -> BlueprintTarget | None:
        if self.cache is None:
            self.cache = self.build_cache()
        for target in self.cache.values():
            if target.block_id == exclude_block_id:
                continue
            if target.path == candidate.path and target.symbol == candidate.symbol and target.kind == candidate.kind:
                return target
        return None

    def update_code_reference(self, target: BlueprintTarget, candidate: CodeTarget) -> None:
        if self.cache is None:
            return
        cached = self.cache.get(target.block_id)
        if cached is None:
            return
        block_data = dict(cached.block_data) if cached.block_data else {}
        code = block_data.setdefault("code", {})
        if isinstance(code, dict):
            code.update(path=candidate.path, symbol=candidate.symbol, kind=candidate.kind)
        self.cache[target.block_id] = BlueprintTarget(
            block_id=cached.block_id,
            path=candidate.path,
            symbol=candidate.symbol,
            kind=candidate.kind,
            source_shard_path=cached.source_shard_path,
            purpose=cached.purpose,
            name=cached.name,
            domain=cached.domain,
            status=cached.status,
            block_data=block_data,
        )

    def remove(self, block_id: str) -> None:
        if self.cache is not None:
            self.cache.pop(block_id, None)


class DriftIssueFactory:
    """Build Inspector issues from Drift Gate evidence without terminal coupling."""

    @staticmethod
    def unit_by_key(snapshot: DiffReviewSnapshot) -> dict[tuple[str, str, str], DiscoveredCodeUnit]:
        if snapshot.scan_result is None:
            return {}
        return {
            (unit.path, unit.symbol, unit.symbol_type): unit
            for unit in snapshot.scan_result.discovered_units
        }

    def from_code_target(
        self,
        item: DiffItem,
        snapshot: DiffReviewSnapshot | None,
        status: str,
        issue_type: str,
        context_line: str,
    ) -> InspectIssue | None:
        code = item.code_target
        if code is None:
            return None
        unit = self.unit_by_key(snapshot).get((code.path, code.symbol, code.kind)) if snapshot is not None else None
        block = build_new_detected_responsibility(unit) if unit is not None else block_from_code_target(code)
        block["status"] = status
        issue = InspectIssue(issue_type=issue_type, block=block, add_on_accept=True)
        issue.context_lines.append(context_line)
        return issue

    def from_candidate(
        self,
        item: DiffItem,
        snapshot: DiffReviewSnapshot | None,
        status: str,
        issue_type: str,
        context_line: str,
    ) -> InspectIssue | None:
        candidate = item.code_target or (item.candidates[0] if item.candidates else None)
        if candidate is None:
            return None
        proxy = DiffItem(
            identifier=item.identifier,
            kind=item.kind,
            action_level=item.action_level,
            risk=item.risk,
            reason=item.reason,
            finding=item.finding,
            code_target=candidate,
        )
        return self.from_code_target(proxy, snapshot, status, issue_type, context_line)

    @staticmethod
    def from_blueprint_target(target: BlueprintTarget, issue_type: str, context_line: str) -> InspectIssue | None:
        if not target.block_data:
            return None
        issue = InspectIssue(issue_type=issue_type, block=target.block_data, add_on_accept=False)
        issue.context_lines.append(context_line)
        return issue
