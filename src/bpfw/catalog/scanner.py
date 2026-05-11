"""Python AST scanner for BPFW MVP Catalog Mode."""

import ast
from pathlib import Path
from typing import Any, Dict, List, Optional

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

    # Sort discovered units so inspect reviews children before parent snippets.
    discovered_units.sort(
        key=_discovered_unit_sort_key
    )

    return ScanResult(
        discovered_units=discovered_units,
        findings=findings,
    )


def _discovered_unit_sort_key(unit: DiscoveredCodeUnit) -> tuple[str, int, int, int, int, str]:
    """Return a stable contained-first order for inspect traversal."""

    end_line = unit.end_line or unit.start_line or 0
    start_line = unit.start_line or 0
    span_size = max(0, end_line - start_line)
    nesting_depth = unit.symbol.count(".")
    return unit.path, end_line, span_size, -nesting_depth, start_line, unit.symbol


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

    discovered_units.extend(
        _extract_code_units(
            nodes=tree.body,
            file_path=str(relative_path),
            module=module,
            imports=imports,
            parent_symbols=[],
            parent_kind=None,
        )
    )

    return discovered_units, findings


def _extract_code_units(
    nodes: List[ast.stmt],
    file_path: str,
    module: str,
    imports: List[str],
    parent_symbols: List[str],
    parent_kind: str | None,
) -> List[DiscoveredCodeUnit]:
    """Extract top-level and nested code units from AST nodes."""

    discovered_units: List[DiscoveredCodeUnit] = []
    for node in nodes:
        if isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue

            symbol_parts = parent_symbols + [node.name]
            unit = _extract_class_unit(
                node=node,
                file_path=file_path,
                module=module,
                imports=imports,
                symbol=".".join(symbol_parts),
                symbol_type=_class_symbol_type(parent_symbols),
            )
            if unit:
                discovered_units.append(unit)
            discovered_units.extend(
                _extract_code_units(
                    nodes=node.body,
                    file_path=file_path,
                    module=module,
                    imports=imports,
                    parent_symbols=symbol_parts,
                    parent_kind="class",
                )
            )
            continue

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_") and not (
                node.name.startswith("__") and node.name.endswith("__")
            ):
                continue

            symbol_parts = parent_symbols + [node.name]
            if _should_discover_function(node=node, parent_kind=parent_kind):
                unit = _extract_function_unit(
                    node=node,
                    file_path=file_path,
                    module=module,
                    imports=imports,
                    symbol=".".join(symbol_parts),
                    symbol_type=_function_symbol_type(
                        parent_symbols=parent_symbols,
                        parent_kind=parent_kind,
                    ),
                )
                if unit:
                    discovered_units.append(unit)
            discovered_units.extend(
                _extract_code_units(
                    nodes=node.body,
                    file_path=file_path,
                    module=module,
                    imports=imports,
                    parent_symbols=symbol_parts,
                    parent_kind="function",
                )
            )

    return discovered_units


def _class_symbol_type(parent_symbols: List[str]) -> str:
    """Return the catalog symbol type for a class node."""

    if parent_symbols:
        return "nested_class"
    return "class"


def _function_symbol_type(parent_symbols: List[str], parent_kind: str | None) -> str:
    """Return the catalog symbol type for a function-like node."""

    if parent_kind == "class":
        return "method"
    if parent_symbols:
        return "nested_function"
    return "function"


def _should_discover_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    parent_kind: str | None,
) -> bool:
    """Return whether a function-like node should become a snippet."""

    if parent_kind == "class" and node.name.startswith("__") and node.name.endswith("__"):
        return False
    return True


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
    symbol: str,
    symbol_type: str,
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
    methods = _extract_direct_child_function_symbols(
        nodes=node.body,
        parent_symbol=symbol,
        skip_dunder=True,
    )
    functions = _extract_direct_child_class_symbols(
        nodes=node.body,
        parent_symbol=symbol,
    )

    # Extract decorators
    decorators = _extract_decorators(node.decorator_list)

    # Extract docstring
    docstring = ast.get_docstring(node)

    # Extract interface metadata
    interface_inputs, interface_output = extract_interface_metadata(
        node=node,
        symbol_type=symbol_type,
        class_body=node.body,
    )

    return DiscoveredCodeUnit(
        path=file_path,
        module=module,
        symbol=symbol,
        symbol_type=symbol_type,
        qualified_name=f"{module}.{symbol}",
        start_line=node.lineno,
        end_line=node.end_lineno if hasattr(node, "end_lineno") else None,
        methods=methods,
        functions=functions,
        imports=imports,
        decorators=decorators,
        docstring=docstring,
        signature=None,
        interface_inputs=interface_inputs,
        interface_output=interface_output,
    )


def _extract_function_unit(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    file_path: str,
    module: str,
    imports: List[str],
    symbol: str,
    symbol_type: str,
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
    functions = _extract_direct_child_symbols(
        nodes=node.body,
        parent_symbol=symbol,
    )

    # Extract interface metadata
    interface_inputs, interface_output = extract_interface_metadata(
        node=node,
        symbol_type=symbol_type,
        class_body=None,
    )

    return DiscoveredCodeUnit(
        path=file_path,
        module=module,
        symbol=symbol,
        symbol_type=symbol_type,
        qualified_name=f"{module}.{symbol}",
        start_line=node.lineno,
        end_line=node.end_lineno if hasattr(node, "end_lineno") else None,
        methods=[],
        functions=functions,
        imports=imports,
        decorators=decorators,
        docstring=docstring,
        signature=signature,
        interface_inputs=interface_inputs,
        interface_output=interface_output,
    )


def _extract_direct_child_symbols(nodes: List[ast.stmt], parent_symbol: str) -> List[str]:
    """Return direct nested snippet symbols for a code unit."""

    child_symbols: List[str] = []
    child_symbols.extend(
        _extract_direct_child_function_symbols(
            nodes=nodes,
            parent_symbol=parent_symbol,
            skip_dunder=False,
        )
    )
    child_symbols.extend(
        _extract_direct_child_class_symbols(
            nodes=nodes,
            parent_symbol=parent_symbol,
        )
    )
    return child_symbols


def _extract_direct_child_function_symbols(
    nodes: List[ast.stmt],
    parent_symbol: str,
    skip_dunder: bool,
) -> List[str]:
    """Return direct nested function-like symbols for a code unit."""

    child_symbols: List[str] = []
    for node in nodes:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_") and not (
            node.name.startswith("__") and node.name.endswith("__")
        ):
            continue
        if skip_dunder and node.name.startswith("__") and node.name.endswith("__"):
            continue
        child_symbols.append(f"{parent_symbol}.{node.name}")
    return child_symbols


def _extract_direct_child_class_symbols(
    nodes: List[ast.stmt],
    parent_symbol: str,
) -> List[str]:
    """Return direct nested class symbols for a code unit."""

    child_symbols: List[str] = []
    for node in nodes:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            child_symbols.append(f"{parent_symbol}.{node.name}")
    return child_symbols


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


def _extract_parameter_annotation(arg: ast.arg) -> Optional[str]:
    """
    Extract type annotation from a parameter as string.

    Args:
        arg: AST arg node.

    Returns:
        Type annotation string or None.
    """
    if arg.annotation is None:
        return None

    try:
        if hasattr(ast, "unparse"):
            return ast.unparse(arg.annotation)
        else:
            return str(arg.annotation)
    except (AttributeError, ValueError, TypeError):
        return None


def _get_default_value(node: ast.FunctionDef | ast.AsyncFunctionDef, arg_name: str) -> Any:
    """
    Get the default value for a parameter as a Python literal.

    Args:
        node: AST FunctionDef or AsyncFunctionDef node.
        arg_name: Parameter name to find.

    Returns:
        Default value (can be any Python literal), or None if no default.
    """
    # Get defaults from args
    # args.args are positional or keyword arguments
    # defaults list aligns with the rightmost args
    defaults = node.args.defaults
    kw_defaults = node.args.kw_defaults
    posonlyargs = node.args.posonlyargs
    args_list = node.args.args
    kwonlyargs = node.args.kwonlyargs

    # Find which argument list contains our parameter
    arg_node = None
    default_index = None

    # Check positional-only args
    for i, arg in enumerate(posonlyargs):
        if arg.arg == arg_name:
            # Positional-only defaults are in the defaults list
            # They're aligned with the rightmost positional args
            num_posonly = len(posonlyargs)
            num_posorkw = len(args_list)
            total_positional = num_posonly + num_posorkw
            if len(defaults) > num_posorkw:
                # Defaults apply to positional-only as well
                idx = i - (total_positional - len(defaults))
                if 0 <= idx < len(defaults):
                    default_node = defaults[idx]
                    return _ast_to_literal(default_node) if default_node is not None else None
            return None

    # Check positional or keyword args
    for i, arg in enumerate(args_list):
        if arg.arg == arg_name:
            # Default index is relative to defaults list
            # defaults align with rightmost args
            num_args = len(args_list)
            if i >= num_args - len(defaults):
                default_index = i - (num_args - len(defaults))
                if 0 <= default_index < len(defaults):
                    default_node = defaults[default_index]
                    return _ast_to_literal(default_node) if default_node is not None else None
            return None

    # Check keyword-only args
    for i, arg in enumerate(kwonlyargs):
        if arg.arg == arg_name:
            if i < len(kw_defaults) and kw_defaults[i] is not None:
                default_node = kw_defaults[i]
                return _ast_to_literal(default_node) if default_node is not None else None
            return None

    # Check *args and **kwargs - they have no defaults
    return None


def _ast_to_literal(node: ast.AST) -> Any:
    """
    Convert an AST literal node to its Python value.

    Args:
        node: AST node representing a literal.

    Returns:
        Python value (None, bool, int, float, str) or the node string if not a simple literal.
    """
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Num):
        return node.n
    if isinstance(node, ast.Str):
        return node.s
    if isinstance(node, ast.NameConstant):
        return node.value
    if isinstance(node, ast.Name):
        # For simple names like None, True, False
        if node.id in ("None", "True", "False"):
            return {"None": None, "True": True, "False": False}[node.id]
    # For more complex expressions, return as string
    try:
        if hasattr(ast, "unparse"):
            return ast.unparse(node)
    except (AttributeError, ValueError, TypeError):
        pass
    return None


def extract_interface_metadata(
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    symbol_type: str,
    class_body: List[ast.stmt] | None = None,
) -> tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Extract interface metadata from a class or function node.

    For classes: extracts from __init__ method if available.
    For functions/methods: extracts from the function signature.

    Args:
        node: AST ClassDef, FunctionDef, or AsyncFunctionDef node.
        symbol_type: Type of symbol ("class", "function", "method", "nested_class", "nested_function").
        class_body: For classes, the list of statements in the class body.

    Returns:
        Tuple of (inputs list, output dict or None).
        Each input is a dict with keys: name, type, default, required, description.
        Output is a dict with keys: type, description, or None.
    """
    # For classes, try to find __init__ and use its signature
    if isinstance(node, ast.ClassDef):
        if class_body is None:
            return [], None

        init_node = None
        for stmt in class_body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name == "__init__":
                init_node = stmt
                break

        if init_node is not None:
            return _extract_function_interface(init_node, skip_self=True)

        # No __init__ found
        return [], None

    # For functions and methods, extract from the signature directly
    skip_self = False
    if symbol_type in ("method", "nested_method"):
        skip_self = True
    return _extract_function_interface(node, skip_self=skip_self)


def _extract_function_interface(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    skip_self: bool = False,
) -> tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Extract interface metadata from a function node.

    Args:
        node: AST FunctionDef or AsyncFunctionDef node.
        skip_self: If True, skip first parameter (for methods).

    Returns:
        Tuple of (inputs list, output dict or None).
    """
    inputs: List[Dict[str, Any]] = []

    # Collect all parameters in order with their default status
    # First, build a mapping of parameter name -> has_default
    defaults_map = _build_defaults_map(node)

    # Collect all parameters in order
    all_params: List[ast.arg] = []

    # Positional-only
    all_params.extend(node.args.posonlyargs)

    # Positional or keyword
    all_params.extend(node.args.args)

    # *args
    if node.args.vararg:
        all_params.append(node.args.vararg)

    # Keyword-only
    all_params.extend(node.args.kwonlyargs)

    # **kwargs
    if node.args.kwarg:
        all_params.append(node.args.kwarg)

    # Skip self/cls if requested
    params_to_process = all_params
    if skip_self and all_params:
        first_param_name = all_params[0].arg
        if first_param_name in ("self", "cls"):
            params_to_process = all_params[1:]

    # Extract each parameter
    for param in params_to_process:
        param_name = param.arg
        param_type = _extract_parameter_annotation(param)
        param_default = _get_default_value(node, param_name)
        # Check if parameter has a default using the defaults map
        # This correctly handles None as a valid default value
        param_required = not defaults_map.get(param_name, False)

        inputs.append({
            "name": param_name,
            "type": param_type,
            "default": param_default,
            "required": param_required,
            "description": None,
        })

    # Extract output type
    output_type = _extract_return_annotation(node)

    output: Optional[Dict[str, Any]] = None
    if output_type is not None:
        output = {
            "type": output_type,
            "description": None,
        }

    return inputs, output


def _build_defaults_map(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, bool]:
    """
    Build a mapping of parameter names to whether they have defaults.

    This correctly distinguishes between parameters with no defaults (required)
    and parameters with default=None (optional).

    Args:
        node: AST FunctionDef or AsyncFunctionDef node.

    Returns:
        Dict mapping parameter names to bool (True if has default).
    """
    defaults_map: dict[str, bool] = {}

    # Process positional or keyword arguments
    # defaults align with rightmost args
    args_list = node.args.args
    defaults = node.args.defaults
    num_args = len(args_list)

    for i, arg in enumerate(args_list):
        # Check if this arg has a default
        if i >= num_args - len(defaults):
            defaults_map[arg.arg] = True  # Has a default
        else:
            defaults_map[arg.arg] = False  # No default

    # Process keyword-only arguments
    # kw_defaults align one-to-one with kwonlyargs
    for i, arg in enumerate(node.args.kwonlyargs):
        if i < len(node.args.kw_defaults) and node.args.kw_defaults[i] is not None:
            defaults_map[arg.arg] = True  # Has a default
        else:
            defaults_map[arg.arg] = False  # No default

    # Positional-only, *args, and **kwargs don't have defaults in the same sense
    # They're always required in different ways

    return defaults_map
