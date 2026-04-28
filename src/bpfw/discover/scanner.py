"""Repository scanner for code-first discover flow."""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path

from bpfw.architecture.architecture_validator import validate_architecture
from bpfw.blueprint.models import BlueprintModel
from bpfw.blueprint.validator import validate_blueprint
from bpfw.duplication.similarity_detector import detect_duplication
from bpfw.duplication.symbol_scanner import scan_project_symbols


IGNORED_DIRECTORIES: set[str] = {
    ".git",
    ".venv",
    "__pycache__",
    "dist",
    "build",
}


@dataclass(slots=True)
class DiscoverFinding:
    """One scanner finding before classification/risk."""

    kind: str
    code: str
    message: str
    file_path: str
    symbol_name: str = ""
    symbol_type: str = ""
    line_number: int = 0
    recommendation: str = ""


@dataclass(slots=True)
class DiscoverScanResult:
    """Raw scanner findings."""

    findings: list[DiscoverFinding] = field(default_factory=list)


def _tracked_scan_roots(project_root: Path) -> list[Path]:
    architecture_result = validate_architecture(project_root=project_root)
    roots: list[Path] = []

    if architecture_result.profile is not None:
        for layer in architecture_result.profile.layers:
            relative_path = layer.path.strip()
            if not relative_path:
                continue
            root_path = (project_root / relative_path).resolve()
            if root_path.exists() and root_path.is_dir():
                roots.append(root_path)

    if not roots:
        fallback_root = (project_root / "src").resolve()
        if fallback_root.exists() and fallback_root.is_dir():
            roots.append(fallback_root)

    unique_roots: list[Path] = []
    for root_path in roots:
        if any(existing == root_path for existing in unique_roots):
            continue
        unique_roots.append(root_path)
    return unique_roots



def _should_ignore_directory(root_relative_parts: tuple[str, ...]) -> bool:
    if not root_relative_parts:
        return False

    normalized_parts = list(root_relative_parts)
    for part in normalized_parts:
        if part in IGNORED_DIRECTORIES:
            return True

    if len(normalized_parts) >= 2 and normalized_parts[0] == ".bpfw" and normalized_parts[1] == "workspaces":
        return True

    return False



def _collect_python_files(project_root: Path) -> list[str]:
    files: list[str] = []
    project_root_resolved = project_root.resolve()

    for scan_root in _tracked_scan_roots(project_root=project_root):
        for current_root, directory_names, file_names in os.walk(scan_root):
            current_root_path = Path(current_root)
            current_root_relative = current_root_path.resolve().relative_to(project_root_resolved)
            if _should_ignore_directory(current_root_relative.parts):
                directory_names[:] = []
                continue

            filtered_directories: list[str] = []
            for directory_name in directory_names:
                candidate_relative = current_root_relative / directory_name
                if _should_ignore_directory(candidate_relative.parts):
                    continue
                filtered_directories.append(directory_name)
            directory_names[:] = filtered_directories

            for file_name in sorted(file_names):
                if not file_name.endswith(".py"):
                    continue
                absolute_path = current_root_path / file_name
                if not absolute_path.exists():
                    continue
                relative_path = absolute_path.resolve().relative_to(project_root_resolved)
                files.append(str(relative_path))

    return sorted(set(files))



def _declared_sets(blueprint: BlueprintModel) -> tuple[set[str], set[str]]:
    declared_files: set[str] = set()
    declared_symbols: set[str] = set()

    for responsibility in blueprint.responsibilities:
        for allowed_file in responsibility.allowed_files:
            if allowed_file:
                declared_files.add(allowed_file)

        for allowed_symbol in responsibility.allowed_symbols:
            if allowed_symbol:
                declared_symbols.add(allowed_symbol)

        for implementation in responsibility.allowed_implementations:
            if implementation.file:
                declared_files.add(implementation.file)
            if implementation.class_name:
                declared_symbols.add(implementation.class_name)

    return declared_files, declared_symbols



def _scan_imports_for_file(project_root: Path, file_path: str) -> list[str]:
    absolute_path = project_root / file_path
    try:
        tree = ast.parse(absolute_path.read_text(encoding="utf-8"), filename=file_path)
    except (OSError, SyntaxError):
        return []

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name_alias in node.names:
                imports.append(name_alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports



def scan_repository(project_root: Path) -> DiscoverScanResult:
    """Scan repository and detect undeclared code-first additions."""

    blueprint_result = validate_blueprint(project_root=project_root)
    if not blueprint_result.is_valid or blueprint_result.blueprint is None:
        first_error = blueprint_result.errors[0]
        return DiscoverScanResult(
            findings=[
                DiscoverFinding(
                    kind="blueprint_change",
                    code="DV100",
                    message=(
                        "Blueprint must be valid before discover can classify undeclared changes: "
                        f"{first_error.message}"
                    ),
                    file_path=first_error.file_path,
                    recommendation=first_error.recommendation,
                )
            ]
        )

    blueprint = blueprint_result.blueprint
    declared_files, declared_symbols = _declared_sets(blueprint=blueprint)
    real_files = _collect_python_files(project_root=project_root)

    findings: list[DiscoverFinding] = []

    undeclared_files: set[str] = set()
    for relative_file_path in real_files:
        if relative_file_path not in declared_files:
            undeclared_files.add(relative_file_path)
            findings.append(
                DiscoverFinding(
                    kind="undeclared_file",
                    code="DV001",
                    message=f"File `{relative_file_path}` is not declared in blueprint responsibilities",
                    file_path=relative_file_path,
                    recommendation="Accept a proposal to attach the file to a responsibility or reject it",
                )
            )

    symbol_result = scan_project_symbols(project_root=project_root)
    for scan_issue in symbol_result.issues:
        findings.append(
            DiscoverFinding(
                kind="scanner_issue",
                code=scan_issue.code,
                message=scan_issue.message,
                file_path=scan_issue.file_path,
                recommendation=scan_issue.recommendation,
            )
        )

    for symbol in symbol_result.symbols:
        qualified_symbol = symbol.qualified_name
        if symbol.symbol_name in declared_symbols or qualified_symbol in declared_symbols:
            continue

        if symbol.file_path in undeclared_files:
            message = (
                f"Symbol `{symbol.symbol_name}` in undeclared file `{symbol.file_path}` "
                "is not declared in blueprint"
            )
        else:
            message = (
                f"Symbol `{symbol.symbol_name}` in declared file `{symbol.file_path}` "
                "is missing from allowed_symbols"
            )

        findings.append(
            DiscoverFinding(
                kind="undeclared_symbol",
                code="DV002",
                message=message,
                file_path=symbol.file_path,
                symbol_name=symbol.symbol_name,
                symbol_type=symbol.symbol_type,
                line_number=symbol.line_number,
                recommendation="Accept proposal and declare symbol, or remove/reject it",
            )
        )

    duplication_result = detect_duplication(project_root=project_root)
    for duplication_finding in duplication_result.findings:
        findings.append(
            DiscoverFinding(
                kind="possible_duplicate",
                code=duplication_finding.code,
                message=duplication_finding.message,
                file_path=duplication_finding.file_path,
                symbol_name=duplication_finding.symbol_name,
                symbol_type=duplication_finding.symbol_type,
                line_number=duplication_finding.line_number,
                recommendation=duplication_finding.recommendation,
            )
        )

    architecture_result = validate_architecture(project_root=project_root)
    for architecture_error in architecture_result.errors:
        findings.append(
            DiscoverFinding(
                kind="architecture_change",
                code=architecture_error.code,
                message=architecture_error.message,
                file_path=architecture_error.file_path,
                recommendation=architecture_error.recommendation,
            )
        )
    for architecture_warning in architecture_result.warnings:
        findings.append(
            DiscoverFinding(
                kind="architecture_change",
                code=architecture_warning.code,
                message=architecture_warning.message,
                file_path=architecture_warning.file_path,
                recommendation=architecture_warning.recommendation,
            )
        )

    for undeclared_file in sorted(undeclared_files):
        for import_name in _scan_imports_for_file(project_root=project_root, file_path=undeclared_file):
            if import_name.startswith("src.") or import_name.startswith("bpfw."):
                continue
            first_token = import_name.split(".", maxsplit=1)[0]
            if first_token in {"typing", "pathlib", "dataclasses", "collections", "itertools", "functools", "json", "os", "re", "ast"}:
                continue
            findings.append(
                DiscoverFinding(
                    kind="dependency_change",
                    code="DV003",
                    message=(
                        f"Possible new dependency import `{import_name}` found in undeclared file `{undeclared_file}`"
                    ),
                    file_path=undeclared_file,
                    recommendation="Confirm dependency is approved before accepting proposal",
                )
            )

    return DiscoverScanResult(findings=findings)
