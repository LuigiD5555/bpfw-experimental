"""Python AST scanner for BPFW MVP Catalog Mode."""

import ast
from pathlib import Path
from typing import List, Optional

from bpfw.catalog.models import DiscoveredCodeUnit, ScanResult
from bpfw.reports.finding import Finding


def scan_python_project(
    project_root: Path,
    source_roots: List[str],
    ignored_paths: List[str],
) -> ScanResult:
    """
    Scan Python project using AST parsing.

    Args:
        project_root: Root directory of the project.
        source_roots: List of source root directories relative to project_root.
        ignored_paths: List of path patterns to ignore.

    Returns:
        ScanResult containing discovered code units and any findings.
    """
    discovered_units: List[DiscoveredCodeUnit] = []
    findings: List[Finding] = []

    for source_root in source_roots:
        source_root_path = project_root / source_root

        # Ignore missing source roots silently
        if not source_root_path.exists():
            continue

        if not source_root_path.is_dir():
            continue

        # Recursively scan .py files
        for py_file in source_root_path.rglob("*.py"):
            file_path = py_file.relative_to(project_root)

            # Skip if any path part matches ignored paths
            if _is_path_ignored(file_path, ignored_paths):
                continue

            # Scan the file
            file_units, file_findings = _scan_python_file(
                project_root,
                py_file,
                file_path,
            )
            discovered_units.extend(file_units)
            findings.extend(file_findings)

    # Sort discovered units by path, symbol_type, symbol
    discovered_units.sort(
        key=lambda u: (u.path, u.symbol_type, u.symbol)
    )

    return ScanResult(
        discovered_units=discovered_units,
        findings=findings,
    )


def _is_path_ignored(file_path: Path, ignored_paths: List[str]) -> bool:
    """
    Check if a file path should be ignored.

    Args:
        file_path: Relative file path to check.
        ignored_paths: List of path patterns to ignore.

    Returns:
        True if the path should be ignored, False otherwise.
    """
    path_parts = file_path.parts

    for ignored in ignored_paths:
        if ignored in path_parts:
            return True

    return False


def _scan_python_file(
    project_root: Path,
    file_path: Path,
    relative_path: Path,
) -> tuple[List[DiscoveredCodeUnit], List[Finding]]:
    """
    Scan a single Python file for code units.

    Args:
        project_root: Root directory of the project.
        file_path: Absolute path to the Python file.
        relative_path: Relative path from project root.

    Returns:
        Tuple of (discovered units, findings).
    """
    discovered_units: List[DiscoveredCodeUnit] = []
    findings: List[Finding] = []

    # Read file with UTF-8 encoding
    try:
        file_content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        findings.append(
            Finding(
                source="bpfw",
                code="PYTHON_READ_ERROR",
                severity="block",
                message="Could not read file with UTF-8 encoding",
                path=str(relative_path),
            )
        )
        return discovered_units, findings

    # Parse AST
    try:
        tree = ast.parse(file_content, filename=str(file_path))
    except SyntaxError as e:
        findings.append(
            Finding(
                source="bpfw",
                code="PYTHON_PARSE_ERROR",
                severity="block",
                message="BPFW could not parse this Python file.",
                path=str(relative_path),
                evidence={
                    "line": e.lineno,
                    "offset": e.offset,
                },
            )
        )
        return discovered_units, findings

    # Extract imports from the module
    imports = _extract_imports(tree)

    # Extract module path
    module = _derive_module_path(relative_path)

    # Scan top-level nodes
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            # Skip private classes
            if node.name.startswith("_"):
                continue

            unit = _extract_class_unit(
                node,
                str(relative_path),
                module,
                imports,
            )
            if unit:
                discovered_units.append(unit)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Skip private functions
            if node.name.startswith("_"):
                continue

            unit = _extract_function_unit(
                node,
                str(relative_path),
                module,
                imports,
            )
            if unit:
                discovered_units.append(unit)

    return discovered_units, findings


def _derive_module_path(relative_path: Path) -> str:
    """
    Derive module path from relative file path.

    Example:
        app/services/users.py -> app.services.users

    Args:
        relative_path: Relative path from project root.

    Returns:
        Module path as dotted string.
    """
    # Remove .py extension and convert to module path
    stem = relative_path.stem
    parent_parts = list(relative_path.parent.parts)
    if parent_parts:
        module = ".".join(parent_parts + [stem])
    else:
        module = stem
    return module


def _extract_imports(tree: ast.AST) -> List[str]:
    """
    Extract and normalize imports from AST.

    Args:
        tree: AST tree.

    Returns:
        List of normalized import strings.
    """
    imports: List[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # Use the full module name, not the alias
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module if node.module else ""
            for alias in node.names:
                if alias.name == "*":
                    # Skip star imports for now
                    continue
                if module:
                    imports.append(f"{module}.{alias.name}")
                else:
                    # Relative import, use name as-is
                    imports.append(alias.name)

    return imports


def _extract_class_unit(
    node: ast.ClassDef,
    file_path: str,
    module: str,
    imports: List[str],
) -> Optional[DiscoveredCodeUnit]:
    """
    Extract class information from AST node.

    Args:
        node: AST ClassDef node.
        file_path: Relative file path.
        module: Module path.
        imports: List of imports from the module.

    Returns:
        DiscoveredCodeUnit or None.
    """
    # Extract methods (excluding dunder methods)
    methods: List[str] = []
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Skip dunder methods (methods that start AND end with __)
            if not (item.name.startswith("__") and item.name.endswith("__")):
                methods.append(item.name)

    # Extract decorators
    decorators = _extract_decorators(node.decorator_list)

    # Extract docstring
    docstring = ast.get_docstring(node)

    return DiscoveredCodeUnit(
        path=file_path,
        module=module,
        symbol=node.name,
        symbol_type="class",
        qualified_name=f"{module}.{node.name}",
        start_line=node.lineno,
        end_line=node.end_lineno if hasattr(node, "end_lineno") else None,
        methods=methods,
        functions=[],
        imports=imports,
        decorators=decorators,
        docstring=docstring,
        signature=None,
    )


def _extract_function_unit(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    file_path: str,
    module: str,
    imports: List[str],
) -> Optional[DiscoveredCodeUnit]:
    """
    Extract function information from AST node.

    Args:
        node: AST FunctionDef or AsyncFunctionDef node.
        file_path: Relative file path.
        module: Module path.
        imports: List of imports from the module.

    Returns:
        DiscoveredCodeUnit or None.
    """
    # Extract decorators
    decorators = _extract_decorators(node.decorator_list)

    # Extract docstring
    docstring = ast.get_docstring(node)

    # Extract signature
    signature = _extract_function_signature(node)

    return DiscoveredCodeUnit(
        path=file_path,
        module=module,
        symbol=node.name,
        symbol_type="function",
        qualified_name=f"{module}.{node.name}",
        start_line=node.lineno,
        end_line=node.end_lineno if hasattr(node, "end_lineno") else None,
        methods=[],
        functions=[],
        imports=imports,
        decorators=decorators,
        docstring=docstring,
        signature=signature,
    )


def _extract_decorators(decorator_list: List[ast.expr]) -> List[str]:
    """
    Extract decorator names from decorator list.

    Args:
        decorator_list: List of decorator AST nodes.

    Returns:
        List of decorator names.
    """
    decorators: List[str] = []

    for decorator in decorator_list:
        if isinstance(decorator, ast.Name):
            decorators.append(decorator.id)
        elif isinstance(decorator, ast.Attribute):
            # Handle @app.route style decorators
            decorators.append(_get_attribute_name(decorator))
        elif isinstance(decorator, ast.Call):
            # Handle @decorator(...) style
            if isinstance(decorator.func, ast.Name):
                decorators.append(decorator.func.id)
            elif isinstance(decorator.func, ast.Attribute):
                decorators.append(_get_attribute_name(decorator.func))
        else:
            # Try to unparse if available
            if hasattr(ast, "unparse"):
                try:
                    decorators.append(ast.unparse(decorator))
                except (AttributeError, ValueError, TypeError):
                    decorators.append("unknown")
            else:
                decorators.append("unknown")

    return decorators


def _get_attribute_name(node: ast.Attribute) -> str:
    """
    Get dotted name from attribute node.

    Args:
        node: AST Attribute node.

    Returns:
        Dotted name string.
    """
    parts = []
    current = node

    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value

    if isinstance(current, ast.Name):
        parts.append(current.id)

    return ".".join(reversed(parts))


def _extract_function_signature(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Optional[str]:
    """
    Extract function signature as string.

    Args:
        node: AST FunctionDef or AsyncFunctionDef node.

    Returns:
        Signature string or None.
    """
    try:
        # Build signature manually for simplicity
        name = node.name
        args_part = _extract_args_string(node)
        return_annotation = _extract_return_annotation(node)

        if return_annotation:
            return f"{name}({args_part}) -> {return_annotation}"
        else:
            return f"{name}({args_part})"
    except (AttributeError, ValueError, TypeError):
        # If we can't safely render, try ast.unparse if available
        if hasattr(ast, "unparse"):
            try:
                return ast.unparse(node)
            except (AttributeError, ValueError, TypeError):
                pass
        return None


def _extract_args_string(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """
    Extract function arguments as string.

    Args:
        node: AST FunctionDef or AsyncFunctionDef node.

    Returns:
        Arguments string.
    """
    args = []
    pos_only = []
    pos_or_kw = []
    kw_only = []
    vararg = None
    kwarg = None

    # Process positional-only arguments
    for arg in node.args.posonlyargs:
        pos_only.append(arg.arg)

    # Process positional or keyword arguments
    for arg in node.args.args:
        pos_or_kw.append(arg.arg)

    # Process keyword-only arguments
    for arg in node.args.kwonlyargs:
        kw_only.append(arg.arg)

    # Process *args
    if node.args.vararg:
        vararg = node.args.vararg.arg

    # Process **kwargs
    if node.args.kwarg:
        kwarg = node.args.kwarg.arg

    # Build the arguments list
    args.extend(pos_only)
    args.extend(pos_or_kw)
    if vararg:
        args.append(f"*{vararg}")
    args.extend(kw_only)
    if kwarg:
        args.append(f"**{kwarg}")

    return ", ".join(args)


def _extract_return_annotation(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Optional[str]:
    """
    Extract return annotation from function node.

    Args:
        node: AST FunctionDef or AsyncFunctionDef node.

    Returns:
        Return annotation string or None.
    """
    if node.returns is None:
        return None

    try:
        if hasattr(ast, "unparse"):
            return ast.unparse(node.returns)
        else:
            # Fallback: simple representation
            return str(node.returns)
    except (AttributeError, ValueError, TypeError):
        return None