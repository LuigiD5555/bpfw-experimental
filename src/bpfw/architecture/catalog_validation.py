"""Catalog validation helpers and CLI entrypoints for BPFW."""

import ast
import importlib
from pathlib import Path

from bpfw.architecture.checker import _check_declared_implementation_existence
from bpfw.catalog.loader import load_catalog_snapshot
from bpfw.catalog.catalog_paths import get_repo_root


def check_implementation_existence_main() -> int:
    """Run implementation existence checks and return process status."""
    violations = _check_declared_implementation_existence()
    if violations:
        print("Implementation existence violations found:")
        for violation in violations:
            print(f"  {violation}")
        return 1
    print("All declared implementations exist.")
    return 0


def resolve_module_source_paths(module_path: str) -> list[Path]:
    """Return repository source files matching a dotted module path."""
    repository_root = get_repo_root()
    module_relative_path = Path(*module_path.split("."))
    module_file_path = repository_root / f"{module_relative_path}.py"
    package_directory_path = repository_root / module_relative_path
    if module_file_path.exists():
        return [module_file_path]
    if package_directory_path.is_dir():
        return sorted(package_directory_path.rglob("*.py"))
    return []


def collect_module_symbols(module_source_path: Path) -> set[str]:
    """Collect top-level assign/function/class symbols from source."""
    try:
        source = module_source_path.read_text(encoding="utf-8")
        syntax_tree = ast.parse(source, filename=str(module_source_path))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return set()

    symbols: set[str] = set()
    for node in syntax_tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    symbols.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            symbols.add(node.target.id)
    return symbols


def module_reference_exists(entrypoint_reference: str) -> bool:
    return bool(resolve_module_source_paths(entrypoint_reference))


def symbol_reference_exists(module_path: str, symbol_name: str) -> bool:
    module_source_paths = resolve_module_source_paths(module_path)
    if not module_source_paths:
        return False
    for module_source_path in module_source_paths:
        if symbol_name in collect_module_symbols(module_source_path):
            return True
    return False


def entrypoint_resolves(entrypoint_reference: str) -> bool:
    try:
        importlib.import_module(entrypoint_reference)
        return True
    except Exception:
        pass

    if module_reference_exists(entrypoint_reference):
        return True

    module_path, separator, attribute_name = entrypoint_reference.rpartition(".")
    if not separator or not module_path or not attribute_name:
        return False

    try:
        module = importlib.import_module(module_path)
    except Exception:
        return False

    if hasattr(module, attribute_name):
        return True
    return symbol_reference_exists(module_path, attribute_name)


def check_entrypoint_implementation_main() -> int:
    """Run entrypoint implementation checks and return process status."""
    catalog_snapshot = load_catalog_snapshot()
    errors: list[str] = []
    for responsibility in catalog_snapshot.responsibilities:
        if not responsibility.is_public:
            continue
        if not responsibility.public_entrypoints:
            errors.append(
                f"[ERROR] {responsibility.responsibility_id}: public responsibility has no entrypoints"
            )
            continue
        for entrypoint_reference in responsibility.public_entrypoints:
            if not entrypoint_resolves(entrypoint_reference):
                errors.append(
                    f"[ERROR] {responsibility.responsibility_id}: "
                    f"entrypoint '{entrypoint_reference}' is not importable"
                )

    if errors:
        print("Entrypoint implementation violations found:")
        for error in errors:
            print(f"  {error}")
        return 1

    print("All declared public entrypoints resolve.")
    return 0

