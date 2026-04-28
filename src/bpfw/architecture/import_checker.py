"""AST-based import checker for architecture layer boundaries."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from bpfw.architecture.layer_rules import is_import_allowed, resolve_layer_for_file
from bpfw.architecture.profile import ArchitectureProfile


@dataclass(slots=True)
class ImportViolation:
    """Blocking architecture import violation."""

    code: str
    message: str
    file_path: str
    recommendation: str


@dataclass(slots=True)
class ImportWarning:
    """Non-blocking architecture warning."""

    code: str
    message: str
    file_path: str
    recommendation: str


@dataclass(slots=True)
class ImportCheckResult:
    """Aggregated import check result."""

    violations: list[ImportViolation] = field(default_factory=list)
    warnings: list[ImportWarning] = field(default_factory=list)



def _is_python_file(path: Path) -> bool:
    return path.is_file() and path.suffix == ".py"



def _resolve_module_to_file(project_root: Path, module_name: str) -> Path | None:
    parts = module_name.split(".")
    if not parts or parts[0] != "src":
        return None

    module_path = Path(*parts)
    candidate_file = project_root / module_path.with_suffix(".py")
    if candidate_file.exists():
        return candidate_file

    candidate_init = project_root / module_path / "__init__.py"
    if candidate_init.exists():
        return candidate_init

    return None



def _collect_import_targets(file_path: Path) -> list[str]:
    source_code = file_path.read_text(encoding="utf-8")
    syntax_tree = ast.parse(source_code, filename=str(file_path))

    targets: list[str] = []
    for node in ast.walk(syntax_tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                targets.append(node.module)
    return targets



def _iter_declared_python_files(project_root: Path, profile: ArchitectureProfile) -> list[Path]:
    files: list[Path] = []
    for layer in profile.layers:
        layer_root = project_root / layer.path
        if not layer_root.exists():
            continue
        files.extend(path for path in layer_root.rglob("*.py") if _is_python_file(path))
    return sorted(set(files))



def check_import_rules(project_root: Path, profile: ArchitectureProfile) -> ImportCheckResult:
    """Validate imports according to architecture layer permissions."""

    result = ImportCheckResult()
    python_files = _iter_declared_python_files(project_root=project_root, profile=profile)

    for python_file in python_files:
        source_layer = resolve_layer_for_file(
            file_path=python_file,
            project_root=project_root,
            layers=profile.layers,
        )
        if source_layer is None:
            result.warnings.append(
                ImportWarning(
                    code="AR005",
                    message="Python file does not belong to any declared layer",
                    file_path=str(python_file),
                    recommendation="Move file under a declared layer path or update architecture profile",
                )
            )
            continue

        try:
            import_targets = _collect_import_targets(python_file)
        except SyntaxError as error:
            result.violations.append(
                ImportViolation(
                    code="AR011",
                    message=f"Syntax error prevents import analysis: {error.msg}",
                    file_path=str(python_file),
                    recommendation="Fix syntax error before architecture check",
                )
            )
            continue

        for module_name in import_targets:
            resolved_file = _resolve_module_to_file(project_root=project_root, module_name=module_name)
            if resolved_file is None:
                continue

            target_layer = resolve_layer_for_file(
                file_path=resolved_file,
                project_root=project_root,
                layers=profile.layers,
            )
            if target_layer is None:
                result.warnings.append(
                    ImportWarning(
                        code="AR008",
                        message=f"Internal import `{module_name}` resolves outside declared layers",
                        file_path=str(python_file),
                        recommendation="Add layer for the imported path or move module into declared layers",
                    )
                )
                continue

            if not is_import_allowed(source_layer=source_layer, target_layer=target_layer):
                result.violations.append(
                    ImportViolation(
                        code="AR006",
                        message=(
                            f"Layer `{source_layer.name}` cannot import layer `{target_layer.name}` "
                            f"via `{module_name}`"
                        ),
                        file_path=str(python_file),
                        recommendation=(
                            f"Remove forbidden import or allow `{target_layer.name}` in "
                            f"`{source_layer.name}.may_import`"
                        ),
                    )
                )

    return result
