"""Change the HTML/CSS discovery granularity of a SQLite authority.

WHY: under the historical "full" profile every HTML element and every CSS rule becomes a block, so
templates produce thousands of wrapper blocks whose content is already covered by their parent's hash.
This module previews (and, on request, applies) a switch to a lighter profile: it lists the declared
HTML/CSS blocks that are discovered today but would no longer be discovered, then removes exactly those
blocks and records the profile in ``project.markup_granularity`` in one authority transaction.

Blocks that are already undiscovered under the current profile are never touched here; they belong to
the normal drift review.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from bpfw.core.catalog.drift import _extract_declared_keys
from bpfw.core.catalog.multilang_scanner import scan_non_python_project
from bpfw.core.catalog.verify import read_ignored_paths, read_markup_granularity, read_source_roots
from bpfw.core.source.tree_sitter_adapter import normalize_markup_granularity

from .store import SqliteAuthorityStore

_MARKUP_LANGUAGES = frozenset({"html", "css"})
_PREVIEW_SAMPLE = 20


def _purpose_kind(block: dict[str, Any]) -> str:
    """Classify a purpose as none, templated (mentions its own path and symbol) or custom."""

    purpose = str(block.get("purpose") or "").strip()
    if not purpose:
        return "none"
    raw_code = block.get("code")
    code: dict[str, Any] = raw_code if isinstance(raw_code, dict) else {}
    path, symbol = str(code.get("path") or ""), str(code.get("symbol") or "")
    if path and symbol and path in purpose and symbol in purpose:
        return "templated"
    return "custom"


def _discovered_markup_keys(project_root: Path, document: dict[str, Any], profile: str) -> set[tuple[str, str, str]]:
    units = scan_non_python_project(
        project_root,
        read_source_roots(document),
        read_ignored_paths(document),
        markup_granularity=profile,
    ).discovered_units
    return {(unit.path, unit.symbol, unit.symbol_type) for unit in units if unit.language in _MARKUP_LANGUAGES}


def plan_regranulation(project_root: Path, store: SqliteAuthorityStore, profile: str) -> dict[str, Any]:
    """Return the blocks a profile switch would remove, without writing anything."""

    target = normalize_markup_granularity(profile)
    document = store.load_document()
    current = read_markup_granularity(document)
    current_keys = _discovered_markup_keys(project_root, document, current)
    target_keys = current_keys if target == current else _discovered_markup_keys(project_root, document, target)
    _declared, declared_by_key = _extract_declared_keys(document)

    removable: list[dict[str, Any]] = []
    for key, block in declared_by_key.items():
        if key in current_keys and key not in target_keys:
            removable.append(block)
    removable_uids = {str(block.get("uid") or block.get("id")) for block in removable}
    referenced_by_kept = sorted({
        str(connection.get("target"))
        for block in document.get("blocks", [])
        if isinstance(block, dict) and str(block.get("uid") or block.get("id")) not in removable_uids
        for connection in (block.get("connections") or [])
        if isinstance(connection, dict) and str(connection.get("target")) in {
            str(candidate.get("id")) for candidate in removable
        }
    })
    purpose_counts: dict[str, int] = {"none": 0, "templated": 0, "custom": 0}
    custom: list[dict[str, Any]] = []
    for block in removable:
        kind = _purpose_kind(block)
        purpose_counts[kind] += 1
        if kind == "custom":
            code = block.get("code") or {}
            custom.append({"id": block.get("id"), "path": code.get("path"), "symbol": code.get("symbol"),
                           "purpose": block.get("purpose")})
    return {
        "current_profile": current,
        "target_profile": target,
        "revision": store.revision(),
        "declared_blocks": len(document.get("blocks", [])),
        "markup_units_current": len(current_keys),
        "markup_units_target": len(target_keys),
        "removable_blocks": len(removable),
        "removable_by_kind": _count_by(removable, lambda block: (block.get("code") or {}).get("kind")),
        "removable_purposes": purpose_counts,
        "custom_purposes": custom,
        "referenced_by_kept_blocks": referenced_by_kept,
        "sample": [
            {"id": block.get("id"), "path": (block.get("code") or {}).get("path"),
             "symbol": (block.get("code") or {}).get("symbol")}
            for block in removable[:_PREVIEW_SAMPLE]
        ],
        "_removable_ids": [block.get("id") for block in removable],
    }


def apply_regranulation(project_root: Path, store: SqliteAuthorityStore, plan: dict[str, Any], *,
                        drop_custom_purposes: bool = False) -> dict[str, Any]:
    """Remove the planned blocks and record the profile in one transaction, after a backup."""

    if plan["referenced_by_kept_blocks"]:
        raise ValueError(
            "Refusing to regranulate: kept blocks still connect to removable blocks: "
            + ", ".join(plan["referenced_by_kept_blocks"][:10])
        )
    if plan["custom_purposes"] and not drop_custom_purposes:
        raise ValueError(
            f"Refusing to regranulate: {len(plan['custom_purposes'])} removable blocks carry a custom purpose; "
            "review them (see custom_purposes), then rerun with --drop-custom-purposes."
        )
    document = store.load_document()
    removable_ids = set(plan["_removable_ids"])
    document["blocks"] = [block for block in document.get("blocks", []) if block.get("id") not in removable_ids]
    project = dict(document.get("project") or {})
    project["markup_granularity"] = plan["target_profile"]
    document["project"] = project

    backup = project_root / ".bpfw" / "backups" / f"authority-before-regranulate-{uuid.uuid4().hex}.sqlite"
    store.backup(backup)
    from bpfw.core.blueprint_engine.engine import BlueprintEngine

    revision = BlueprintEngine(project_root).replace_authority_document(
        document,
        reason=f"regranulate markup discovery to {plan['target_profile']}",
        expected_revision=plan["revision"],
    )
    return {"applied": True, "removed_blocks": len(removable_ids), "revision": revision, "backup": str(backup)}


def public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Drop internal keys before printing a plan."""

    return {key: value for key, value in plan.items() if not key.startswith("_")}


def _count_by(blocks: list[dict[str, Any]], key_of: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for block in blocks:
        key = str(key_of(block))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))
