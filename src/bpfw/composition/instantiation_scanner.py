"""Heuristic scanner for concrete class instantiations."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from bpfw.blueprint.models import BlueprintModel


@dataclass(slots=True)
class InstantiationHit:
    """Detected concrete class instantiation call."""

    file_path: Path
    class_name: str


@dataclass(slots=True)
class InstantiationScanResult:
    """Scanner output with collected instantiations."""

    hits: list[InstantiationHit] = field(default_factory=list)



def _class_names_in_file(file_path: Path) -> set[str]:
    source_code = file_path.read_text(encoding="utf-8")
    syntax_tree = ast.parse(source_code, filename=str(file_path))
    return {node.name for node in ast.walk(syntax_tree) if isinstance(node, ast.ClassDef)}



def _call_names_in_file(file_path: Path) -> list[str]:
    source_code = file_path.read_text(encoding="utf-8")
    syntax_tree = ast.parse(source_code, filename=str(file_path))

    call_names: list[str] = []
    for node in ast.walk(syntax_tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            call_names.append(node.func.id)
    return call_names



def _infrastructure_class_names(project_root: Path) -> set[str]:
    infrastructure_root = project_root / "src/infrastructure"
    if not infrastructure_root.exists():
        return set()

    class_names: set[str] = set()
    for file_path in infrastructure_root.rglob("*.py"):
        if not file_path.is_file():
            continue
        try:
            class_names.update(_class_names_in_file(file_path))
        except SyntaxError:
            continue
    return class_names



def _blueprint_concrete_class_names(blueprint: BlueprintModel) -> set[str]:
    class_names: set[str] = set()
    for responsibility in blueprint.responsibilities:
        for implementation in responsibility.allowed_implementations:
            if implementation.class_name:
                class_names.add(implementation.class_name)
    return class_names



def scan_concrete_instantiations(project_root: Path, blueprint: BlueprintModel) -> InstantiationScanResult:
    """Scan repository Python files looking for concrete class constructor calls."""

    tracked_concrete_names = _infrastructure_class_names(project_root=project_root)
    tracked_concrete_names.update(_blueprint_concrete_class_names(blueprint=blueprint))

    result = InstantiationScanResult()
    for file_path in (project_root / "src").rglob("*.py"):
        if not file_path.is_file():
            continue

        try:
            local_class_names = _class_names_in_file(file_path)
            call_names = _call_names_in_file(file_path)
        except SyntaxError:
            continue

        for call_name in call_names:
            if call_name not in tracked_concrete_names:
                continue
            if call_name in local_class_names:
                continue
            result.hits.append(InstantiationHit(file_path=file_path, class_name=call_name))

    return result
