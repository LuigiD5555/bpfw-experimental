"""PURPOSE connection detection for planner flow inference
DOMAIN  planner workflow
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from bpfw.integrations.planner.models import PlannerBox


@dataclass(frozen=True)
class InferredConnection:
    """PURPOSE connection inferred from static analysis
    DOMAIN  planner workflow
    """

    source_box_id: str
    target_box_id: str
    relationship: str
    confidence: str
    evidence: List[str] = field(default_factory=list)


@dataclass
class _FileFacts:
    """PURPOSE minimal static facts for a scanned file
    DOMAIN  planner workflow
    """

    imports: Set[str] = field(default_factory=set)
    calls: Set[str] = field(default_factory=set)


def detect_connections(
    boxes: List[PlannerBox],
    project_root: Path,
    source_roots: List[str],
    ignored_paths: List[str],
) -> List[InferredConnection]:
    """PURPOSE infer box connections from Python imports and call-sites
    DOMAIN  planner workflow
    """

    if not boxes:
        return []

    box_by_module_symbol: Dict[Tuple[str, str], PlannerBox] = {}
    box_by_qualified_name: Dict[str, PlannerBox] = {}
    boxes_by_module: Dict[str, List[PlannerBox]] = {}

    for box in boxes:
        if box.qualified_name:
            box_by_qualified_name[box.qualified_name] = box
        if box.module and box.symbol:
            box_by_module_symbol[(box.module, box.symbol)] = box
        if box.module:
            boxes_by_module.setdefault(box.module, []).append(box)

    file_facts = _scan_project_files(
        project_root=project_root,
        source_roots=source_roots,
        ignored_paths=ignored_paths,
    )
    if not file_facts:
        return []

    inferred: Dict[Tuple[str, str, str], InferredConnection] = {}
    for box in boxes:
        if not box.module:
            continue
        facts = file_facts.get(box.module)
        if not facts:
            continue

        # High confidence: a known symbol from another box is called.
        for called_symbol in sorted(facts.calls):
            target = _resolve_called_symbol(
                called_symbol=called_symbol,
                current_module=box.module,
                box_by_module_symbol=box_by_module_symbol,
                box_by_qualified_name=box_by_qualified_name,
            )
            if not target or target.id == box.id:
                continue
            _upsert_inferred(
                inferred=inferred,
                source_box_id=box.id,
                target_box_id=target.id,
                relationship="uses",
                confidence="high",
                evidence=f"call:{called_symbol}",
            )

        # Medium confidence: imported module belongs to known target box/module.
        for imported_module in sorted(facts.imports):
            for target_box in boxes_by_module.get(imported_module, []):
                if target_box.id == box.id:
                    continue
                _upsert_inferred(
                    inferred=inferred,
                    source_box_id=box.id,
                    target_box_id=target_box.id,
                    relationship="depends_on",
                    confidence="medium",
                    evidence=f"import:{imported_module}",
                )

    return list(inferred.values())


def _scan_project_files(
    project_root: Path,
    source_roots: List[str],
    ignored_paths: List[str],
) -> Dict[str, _FileFacts]:
    """PURPOSE scan python files and gather import/call facts keyed by module
    DOMAIN  planner workflow
    """

    facts_by_module: Dict[str, _FileFacts] = {}
    ignored = set(ignored_paths)

    for source_root in source_roots:
        source_root_path = project_root / source_root
        if not source_root_path.exists() or not source_root_path.is_dir():
            continue

        for py_file in source_root_path.rglob("*.py"):
            relative_path = py_file.relative_to(project_root)
            if any(part in ignored for part in relative_path.parts):
                continue

            module = str(relative_path).replace("\\", "/").replace(".py", "").replace("/", ".")
            parsed = _parse_file(py_file)
            if not parsed:
                continue
            facts_by_module[module] = parsed

    return facts_by_module


def _parse_file(path: Path) -> Optional[_FileFacts]:
    """PURPOSE parse a Python file and extract imports and calls
    DOMAIN  planner workflow
    """

    try:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(path))
    except (UnicodeDecodeError, SyntaxError):
        return None

    facts = _FileFacts()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                facts.imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                facts.imports.add(node.module)
        elif isinstance(node, ast.Call):
            called_name = _extract_called_name(node.func)
            if called_name:
                facts.calls.add(called_name)
    return facts


def _extract_called_name(func_node: ast.expr) -> Optional[str]:
    """PURPOSE get a best-effort called symbol name
    DOMAIN  planner workflow
    """

    if isinstance(func_node, ast.Name):
        return func_node.id
    if isinstance(func_node, ast.Attribute):
        parts: List[str] = []
        current: Optional[ast.expr] = func_node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        parts.reverse()
        return ".".join(parts)
    return None


def _resolve_called_symbol(
    called_symbol: str,
    current_module: str,
    box_by_module_symbol: Dict[Tuple[str, str], PlannerBox],
    box_by_qualified_name: Dict[str, PlannerBox],
) -> Optional[PlannerBox]:
    """PURPOSE find a called symbol to a target box using known mappings
    DOMAIN  planner workflow
    """

    if called_symbol in box_by_qualified_name:
        return box_by_qualified_name[called_symbol]

    # Unqualified symbol: assume local module function/class call.
    if "." not in called_symbol:
        return box_by_module_symbol.get((current_module, called_symbol))

    # Try module.symbol from dotted call like module.symbol(...)
    prefix, _, symbol = called_symbol.rpartition(".")
    if prefix and symbol:
        direct = box_by_module_symbol.get((prefix, symbol))
        if direct:
            return direct
    return None


def _upsert_inferred(
    inferred: Dict[Tuple[str, str, str], InferredConnection],
    source_box_id: str,
    target_box_id: str,
    relationship: str,
    confidence: str,
    evidence: str,
) -> None:
    """PURPOSE insert/merge an inferred connection by identity
    DOMAIN  planner workflow
    """

    key = (source_box_id, target_box_id, relationship)
    current = inferred.get(key)
    if not current:
        inferred[key] = InferredConnection(
            source_box_id=source_box_id,
            target_box_id=target_box_id,
            relationship=relationship,
            confidence=confidence,
            evidence=[evidence],
        )
        return

    merged_evidence = list(current.evidence)
    if evidence not in merged_evidence:
        merged_evidence.append(evidence)
    inferred[key] = InferredConnection(
        source_box_id=current.source_box_id,
        target_box_id=current.target_box_id,
        relationship=current.relationship,
        confidence=_pick_higher_confidence(current.confidence, confidence),
        evidence=merged_evidence,
    )


def _pick_higher_confidence(left: str, right: str) -> str:
    """PURPOSE get highest confidence between two levels
    DOMAIN  planner workflow
    """

    rank = {"low": 0, "medium": 1, "high": 2}
    return left if rank.get(left, 0) >= rank.get(right, 0) else right
