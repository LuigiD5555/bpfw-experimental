"""PURPOSE review service that converts verify findings into diff items
DOMAIN  optional integrations
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bpfw.core.authority import AuthorityRepository, ShardDecisionEngine
from bpfw.core.authority.errors import AuthorityError
from bpfw.core.catalog.loader import BlueprintLoader
from bpfw.core.catalog.models import BlueprintLoadResult, DiscoveredCodeUnit, ScanResult, VerificationReport
from bpfw.core.catalog.verify import run_verify, scan_project_from_blueprint
from bpfw.integrations.diff.models import (
    DiffActionLevel,
    BlueprintTarget,
    CodeTarget,
    DiffItem,
    DiffItemKind,
    DiffRisk,
)
from bpfw.reports.finding import Finding


@dataclass(frozen=True)
class DiffReviewSnapshot:
    """PURPOSE loaded state used by one diff session
    DOMAIN  optional integrations
    """

    project_root: Path
    load_result: BlueprintLoadResult
    scan_result: ScanResult | None
    verify_report: VerificationReport
    blueprint_data: dict[str, Any]
    authority_document: Any | None
    items: tuple[DiffItem, ...]


class DiffReviewService:
    """PURPOSE build the read-only difference list consumed by bpfw diff
    DOMAIN  optional integrations
    """

    def __init__(self, project_root: Path) -> None:
        """PURPOSE set up the service
        DOMAIN  optional integrations
        """
        self.project_root = project_root.resolve()

    def load(self) -> DiffReviewSnapshot:
        """PURPOSE read authority, scan code, verify, and build diff items
        DOMAIN  optional integrations
        """
        loader = BlueprintLoader(project_root=self.project_root)
        load_result = loader.load()
        blueprint_data = load_result.data
        authority_document = None
        scan_result = None

        if load_result.state not in {"missing", "invalid"}:
            try:
                repository = AuthorityRepository(self.project_root)
                authority_document = repository.load()
                blueprint_data = authority_document.blueprint_data
            except (FileNotFoundError, ValueError, AuthorityError):
                authority_document = None
            scan_result = scan_project_from_blueprint(
                project_root=self.project_root,
                blueprint_data=blueprint_data,
                domain_document=load_result.domain_document,
            )

        verify_report, _exit_code = run_verify(
            project_root=self.project_root,
            precomputed_scan_result=scan_result,
        )
        items = self._build_items(
            load_result=load_result,
            blueprint_data=blueprint_data,
            authority_document=authority_document,
            scan_result=scan_result,
            verify_findings=verify_report.findings,
        )
        return DiffReviewSnapshot(
            project_root=self.project_root,
            load_result=load_result,
            scan_result=scan_result,
            verify_report=verify_report,
            blueprint_data=blueprint_data,
            authority_document=authority_document,
            items=tuple(items),
        )


    def from_loaded_context(
        self,
        load_result: BlueprintLoadResult,
        blueprint_data: dict[str, Any],
        authority_document: Any | None,
        scan_result: ScanResult | None,
        verify_report: VerificationReport,
    ) -> DiffReviewSnapshot:
        """PURPOSE build a diff snapshot from already-loaded inspector context
        DOMAIN  optional integrations
        """
        items = self._build_items(
            load_result=load_result,
            blueprint_data=blueprint_data,
            authority_document=authority_document,
            scan_result=scan_result,
            verify_findings=verify_report.findings,
        )
        return DiffReviewSnapshot(
            project_root=self.project_root,
            load_result=load_result,
            scan_result=scan_result,
            verify_report=verify_report,
            blueprint_data=blueprint_data,
            authority_document=authority_document,
            items=tuple(items),
        )

    def _build_items(
        self,
        load_result: BlueprintLoadResult,
        blueprint_data: dict[str, Any],
        authority_document: Any | None,
        scan_result: ScanResult | None,
        verify_findings: list[Finding],
    ) -> list[DiffItem]:
        """PURPOSE build diff items from verification findings
        DOMAIN  optional integrations
        """
        discovered_units = scan_result.discovered_units if scan_result is not None else []
        discovered_by_key = {
            (unit.path, unit.symbol, unit.symbol_type): unit
            for unit in discovered_units
        }
        blocks = _read_blocks(blueprint_data)
        block_by_id = {
            str(block.get("id")): block
            for block in blocks
            if isinstance(block.get("id"), str) and block.get("id")
        }
        items: list[DiffItem] = []

        if load_result.state == "missing":
            items.append(
                DiffItem(
                    identifier="invalid-authority-0",
                    kind=DiffItemKind.INVALID_AUTHORITY,
                    action_level=DiffActionLevel.HUMAN_DECISION,
                    risk=DiffRisk.HIGH,
                    reason="No BPFW blueprint file was found.",
                    finding=load_result.findings[0] if load_result.findings else None,
                )
            )
            return items

        sequence_by_kind: dict[str, int] = {}
        for finding in verify_findings:
            item = self._build_item_from_finding(
                finding=finding,
                sequence_by_kind=sequence_by_kind,
                block_by_id=block_by_id,
                blocks=blocks,
                authority_document=authority_document,
                discovered_by_key=discovered_by_key,
                discovered_units=discovered_units,
            )
            if item is not None:
                items.append(item)
        return _order_undeclared_items_by_scan_review_order(items, discovered_units)

    def _build_item_from_finding(
        self,
        finding: Finding,
        sequence_by_kind: dict[str, int],
        block_by_id: dict[str, dict[str, Any]],
        blocks: list[dict[str, Any]],
        authority_document: Any | None,
        discovered_by_key: dict[tuple[str, str, str], DiscoveredCodeUnit],
        discovered_units: list[DiscoveredCodeUnit],
    ) -> DiffItem | None:
        """PURPOSE convert one verify finding into a diff item
        DOMAIN  optional integrations
        """
        item_kind = _map_finding_code(finding.code)
        if item_kind is None:
            return None

        sequence = sequence_by_kind.get(item_kind.value, 0) + 1
        sequence_by_kind[item_kind.value] = sequence
        identifier = f"{item_kind.value.lower()}-{sequence}"

        if item_kind == DiffItemKind.UNDECLARED_CODE:
            code_target = self._code_target_for_finding(finding, discovered_by_key)
            return DiffItem(
                identifier=identifier,
                kind=item_kind,
                action_level=DiffActionLevel.HUMAN_DECISION,
                risk=DiffRisk.LOW,
                reason="Code exists but no authority block declares it.",
                finding=finding,
                code_target=code_target,
            )

        if item_kind == DiffItemKind.MISSING_DECLARED_CODE:
            blueprint_target = self._blueprint_target_for_finding(
                finding=finding,
                blocks=blocks,
                authority_document=authority_document,
            )
            candidates = self._matching_code_candidates(
                finding=finding,
                discovered_units=discovered_units,
            )
            display_kind = DiffItemKind.MOVED_CODE_CANDIDATE if candidates else item_kind
            if candidates:
                identifier = f"{display_kind.value.lower()}-{sequence}"
            return DiffItem(
                identifier=identifier,
                kind=display_kind,
                action_level=DiffActionLevel.HUMAN_DECISION,
                risk=DiffRisk.HIGH if candidates else DiffRisk.MEDIUM,
                reason=(
                    "Blueprint code was not found, but a possible moved-code candidate exists."
                    if candidates
                    else "Blueprint declares code that was not found in the project."
                ),
                finding=finding,
                blueprint_target=blueprint_target,
                code_target=candidates[0] if candidates else None,
                candidates=tuple(candidates),
            )

        if item_kind == DiffItemKind.DUPLICATE_ACTIVE_PURPOSE:
            active_ids = finding.evidence.get("active_block_ids", [])
            related_blocks = tuple(
                self._blueprint_target_for_block(block_by_id[block_id], authority_document)
                for block_id in active_ids
                if isinstance(block_id, str) and block_id in block_by_id
            )
            return DiffItem(
                identifier=identifier,
                kind=item_kind,
                action_level=DiffActionLevel.HUMAN_DECISION,
                risk=DiffRisk.HIGH,
                reason="Two or more active blocks claim the same purpose.",
                finding=finding,
                related_blocks=related_blocks,
            )

        return DiffItem(
            identifier=identifier,
            kind=item_kind,
            action_level=_action_level_for_kind(item_kind),
            risk=DiffRisk.HIGH,
            reason=finding.message,
            finding=finding,
            blueprint_target=self._blueprint_target_for_finding(
                finding=finding,
                blocks=blocks,
                authority_document=authority_document,
            ),
        )

    def _code_target_for_finding(
        self,
        finding: Finding,
        discovered_by_key: dict[tuple[str, str, str], DiscoveredCodeUnit],
    ) -> CodeTarget | None:
        """PURPOSE find the code target for an undeclared-code finding
        DOMAIN  optional integrations
        """
        kind = str(finding.evidence.get("kind", ""))
        if finding.path is None or finding.symbol is None or not kind:
            return None
        unit = discovered_by_key.get((finding.path, finding.symbol, kind))
        if unit is None:
            return CodeTarget(path=finding.path, symbol=finding.symbol, kind=kind)
        return _code_target_from_unit(unit)

    def _blueprint_target_for_finding(
        self,
        finding: Finding,
        blocks: list[dict[str, Any]],
        authority_document: Any | None,
    ) -> BlueprintTarget | None:
        """PURPOSE find the authority target for a finding
        DOMAIN  optional integrations
        """
        if finding.symbol:
            for block in blocks:
                code = block.get("code")
                if not isinstance(code, dict):
                    continue
                if code.get("path") == finding.path and code.get("symbol") == finding.symbol:
                    return self._blueprint_target_for_block(block, authority_document)
                if block.get("id") == finding.symbol:
                    return self._blueprint_target_for_block(block, authority_document)
        return None

    def _blueprint_target_for_block(
        self,
        block: dict[str, Any],
        authority_document: Any | None,
    ) -> BlueprintTarget:
        """PURPOSE build a blueprint target from one block dictionaryionary
                DOMAIN  optional integrations

        """
        code = block.get("code") if isinstance(block.get("code"), dict) else {}
        block_id = str(block.get("id", ""))
        source_shard_path = None
        if authority_document is not None and block_id:
            source_shard_path = authority_document.get_origin(block_id)
        return BlueprintTarget(
            block_id=block_id,
            path=_optional_string(code.get("path")),
            symbol=_optional_string(code.get("symbol")),
            kind=_optional_string(code.get("kind")),
            source_shard_path=source_shard_path,
            purpose=_optional_string(block.get("purpose")),
            name=_optional_string(block.get("name")),
            domain=_optional_string(block.get("domain")),
            status=_optional_string(block.get("status")) or _optional_string(block.get("lifecycle")),
            block_data=dict(block),
        )

    def _matching_code_candidates(
        self,
        finding: Finding,
        discovered_units: list[DiscoveredCodeUnit],
    ) -> list[CodeTarget]:
        """PURPOSE find simple moved-code candidates for a missing declaration
        DOMAIN  optional integrations
        """
        if finding.symbol is None:
            return []
        symbol_tail = finding.symbol.split(".")[-1]
        candidates: list[CodeTarget] = []
        for unit in discovered_units:
            if unit.symbol == finding.symbol or unit.symbol.split(".")[-1] == symbol_tail:
                candidates.append(_code_target_from_unit(unit))
        return candidates[:5]

    def decide_shard_for_block(
        self,
        blueprint_data: dict[str, Any],
        authority_document: Any | None,
        block_data: dict[str, Any],
    ) -> Path:
        """PURPOSE get the shard where a block should be stored
        DOMAIN  optional integrations
        """
        authority_config = blueprint_data.get("authority")
        if not isinstance(authority_config, dict):
            authority_config = {}
        decision_engine = ShardDecisionEngine(authority_config)
        return decision_engine.decide_shard_for_block(block_data, authority_document)


def _map_finding_code(code: str) -> DiffItemKind | None:
    """PURPOSE map a verification code to a diff item kind
    DOMAIN  optional integrations
    """
    mapping = {
        "UNDECLARED_CODE": DiffItemKind.UNDECLARED_CODE,
        "MISSING_DECLARED_CODE": DiffItemKind.MISSING_DECLARED_CODE,
        "DUPLICATE_ACTIVE_PURPOSE": DiffItemKind.DUPLICATE_ACTIVE_PURPOSE,
        "INCOMPLETE_BLOCK": DiffItemKind.INCOMPLETE_METADATA,
        "INVALID_STATUS": DiffItemKind.INCOMPLETE_METADATA,
        "DUPLICATE_BLOCK_ID": DiffItemKind.INVALID_AUTHORITY,
        "DUPLICATE_CODE_DECLARATION": DiffItemKind.INVALID_AUTHORITY,
        "INVALID_SHARD": DiffItemKind.INVALID_AUTHORITY,
        "INCLUDE_FILE_MISSING": DiffItemKind.BROKEN_SHARD_REFERENCE,
    }
    return mapping.get(code)


def _action_level_for_kind(item_kind: DiffItemKind) -> DiffActionLevel:
    """PURPOSE get the handling level for one diff item kind
    DOMAIN  optional integrations
    """
    if item_kind == DiffItemKind.METADATA_DRIFT:
        return DiffActionLevel.READ_ONLY
    return DiffActionLevel.HUMAN_DECISION


def _read_blocks(blueprint_data: dict[str, Any]) -> list[dict[str, Any]]:
    """PURPOSE get authority blocks from blueprint data
    DOMAIN  optional integrations
    """
    blocks = blueprint_data.get("blocks")
    if not isinstance(blocks, list):
        return []
    return [block for block in blocks if isinstance(block, dict)]


def _code_target_from_unit(unit: DiscoveredCodeUnit) -> CodeTarget:
    """PURPOSE build a code target from one discovered unit
    DOMAIN  optional integrations
    """
    return CodeTarget(
        path=unit.path,
        symbol=unit.symbol,
        kind=unit.symbol_type,
        start_line=unit.start_line,
        end_line=unit.end_line,
        qualified_name=unit.qualified_name,
    )


def _order_undeclared_items_by_scan_review_order(
    items: list[DiffItem],
    discovered_units: list[DiscoveredCodeUnit],
) -> list[DiffItem]:
    """PURPOSE order undeclared-code items with the scanner review order
    DOMAIN  optional integrations
    """
    if not items or not discovered_units:
        return items

    rank_by_key = {
        (unit.path, unit.symbol, unit.symbol_type): index
        for index, unit in enumerate(discovered_units)
    }
    undeclared_items = [item for item in items if item.kind == DiffItemKind.UNDECLARED_CODE]
    if len(undeclared_items) < 2:
        return items

    ordered_undeclared = sorted(
        undeclared_items,
        key=lambda item: _scan_rank_for_item(item, rank_by_key),
    )
    ordered_iterator = iter(ordered_undeclared)
    reordered: list[DiffItem] = []
    for item in items:
        if item.kind == DiffItemKind.UNDECLARED_CODE:
            reordered.append(next(ordered_iterator))
        else:
            reordered.append(item)
    return reordered


def _scan_rank_for_item(
    item: DiffItem,
    rank_by_key: dict[tuple[str, str, str], int],
) -> tuple[int, str, str, str]:
    """PURPOSE get a stable scan-order rank for one diff item
    DOMAIN  optional integrations
    """
    target = item.code_target
    if target is None:
        return len(rank_by_key), "", "", ""
    key = (target.path or "", target.symbol or "", target.kind or "")
    return (
        rank_by_key.get(key, len(rank_by_key)),
        target.path or "",
        target.symbol or "",
        target.kind or "",
    )


def _optional_string(value: Any) -> str | None:
    """PURPOSE get a non-empty string or None
    DOMAIN  optional integrations
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None
