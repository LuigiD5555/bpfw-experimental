"""PURPOSE Python code scanner for BPFW catalog mode
DOMAIN  blueprint checks
"""

import ast
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from bpfw.core.catalog.models import DiscoveredCodeUnit, ScanResult
from bpfw.core.catalog.review_order import order_blocks_for_review
from bpfw.reports.finding import Finding


def scan_python_project(
    project_root: Path,
    source_roots: List[str],
    ignored_paths: List[str],
) -> ScanResult:
    """PURPOSE scan Python project by reading Python code structure
    DOMAIN  blueprint checks
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

    # Sort discovered units using dependency-first topological ordering.
    # Dependencies are reviewed before dependents for better context.
    discovered_units = order_blocks_for_review(discovered_units)

    return ScanResult(
        discovered_units=discovered_units,
        findings=findings,
    )


def _is_path_ignored(file_path: Path, ignored_paths: List[str]) -> bool:
    """PURPOSE check if a file path should be ignored
    DOMAIN  blueprint checks
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
    """PURPOSE scan a single Python file for code units
    DOMAIN  blueprint checks
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
            source_text=file_content,
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
    source_text: str,
) -> List[DiscoveredCodeUnit]:
    """PURPOSE get main and nested code units from Python code nodes
    DOMAIN  blueprint checks
    """

    discovered_units: List[DiscoveredCodeUnit] = []
    for node in nodes:
        if isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            # Filter out data classes (classes with no instance methods)
            if _is_data_class(node):
                continue
            # Filter out protocols and abstract classes
            if _is_protocol_or_abstract_class(node):
                continue

            symbol_parts = parent_symbols + [node.name]
            unit = _extract_class_unit(
                node=node,
                file_path=file_path,
                module=module,
                imports=imports,
                symbol=".".join(symbol_parts),
                symbol_type=_class_symbol_type(parent_symbols),
                source_text=source_text,
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
                    source_text=source_text,
                )
            )
            continue

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Filter out private methods (except dunder methods)
            if node.name.startswith("_") and not (
                node.name.startswith("__") and node.name.endswith("__")
            ):
                continue
            # Filter out nested functions in decorators
            if _is_decorator_nested_function(node, parent_kind, parent_symbols):
                continue
            # Filter out tiny nested functions (< 5 lines of code)
            if parent_kind == "function" and _is_tiny_nested_function(node):
                continue
            # Filter out trivial methods (getters/setters with minimal logic)
            if parent_kind == "class" and _is_trivial_method(node):
                continue
            # Filter out property-like methods in schema.py
            if _is_schema_wrapper_function(node, module):
                continue

            symbol_parts = parent_symbols + [node.name]
            if _should_discover_function(node=node, parent_kind=parent_kind, module=module):
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
                    source_text=source_text,
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
                    source_text=source_text,
                )
            )

    return discovered_units


def _is_trivial_method(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """PURPOSE check if a method is trivial (getter/setter with minimal logic)
    DOMAIN  blueprint checks
    """
    # Count actual code lines (excluding decorators and docstring)
    code_lines = 0
    for stmt in node.body:
        # Skip docstring if it's the first statement
        if code_lines == 0 and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            if isinstance(stmt.value.value, str):
                continue

        code_lines += 1

        # Check for complex structures
        if isinstance(stmt, (ast.For, ast.While, ast.If, ast.Try, ast.With)):
            return False  # Has complex control flow
    # Consider trivial if no actual code lines (only docstring)
    return code_lines < 1


def _is_tiny_nested_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """PURPOSE check if a nested function is too small to be a separate block
    DOMAIN  blueprint checks
    """
    # Count total lines in body
    total_lines = 0
    for stmt in node.body:
        # Skip docstring if it's the first statement
        if total_lines == 0 and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            if isinstance(stmt.value.value, str):
                continue
        total_lines += 1
    # Consider tiny if empty (no actual code, only docstring)
    return total_lines < 1


def _class_symbol_type(parent_symbols: List[str]) -> str:
    """PURPOSE get the catalog symbol type for a class node
    DOMAIN  blueprint checks
    """

    if parent_symbols:
        return "nested_class"
    return "class"


def _function_symbol_type(parent_symbols: List[str], parent_kind: str | None) -> str:
    """PURPOSE get the catalog symbol type for a function-like node
    DOMAIN  blueprint checks
    """

    if parent_kind == "class":
        return "method"
    if parent_symbols:
        return "nested_function"
    return "function"


def _normalized_body_hash(node: ast.AST) -> str:
    """PURPOSE get a stable hash for a code unit body independent of its name
    DOMAIN  blueprint checks
    """
    body = getattr(node, "body", [])
    normalized_module = ast.Module(body=list(body), type_ignores=[])
    normalized_dump = ast.dump(normalized_module, include_attributes=False)
    return hashlib.sha256(normalized_dump.encode("utf-8")).hexdigest()


def _detect_dangerous_capabilities(node: ast.AST) -> dict[str, bool]:
    """PURPOSE find high-risk side-effect capabilities used by a code unit
    DOMAIN  blueprint checks
    """
    capabilities = {
        "writes_files": False,
        "deletes_files": False,
        "opens_network": False,
        "uses_subprocess": False,
    }
    dangerous_delete_names = {"remove", "unlink", "rmtree", "rmdir"}
    network_roots = {"socket", "requests", "httpx", "urllib"}

    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        call_name = _call_name(child.func)
        if call_name is None:
            continue
        if call_name.startswith("subprocess.") or call_name in {"run", "Popen", "call", "check_call", "check_output"}:
            capabilities["uses_subprocess"] = True
        if call_name in {"open", "Path.open"} or call_name.endswith(".open"):
            if _call_uses_write_mode(child):
                capabilities["writes_files"] = True
        if any(call_name == name or call_name.endswith(f".{name}") for name in dangerous_delete_names):
            capabilities["deletes_files"] = True
        if any(call_name == root or call_name.startswith(f"{root}.") for root in network_roots):
            capabilities["opens_network"] = True

    return capabilities


def _call_name(node: ast.AST) -> str | None:
    """PURPOSE get a dotted call name from an Python code expression
        DOMAIN  blueprint checks

    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent_name = _call_name(node.value)
        if parent_name is None:
            return node.attr
        return f"{parent_name}.{node.attr}"
    return None


def _call_uses_write_mode(node: ast.Call) -> bool:
    """PURPOSE check whether an open-like call uses a write-capable mode
    DOMAIN  blueprint checks
    """
    write_modes = {"w", "a", "x", "+"}
    candidate_values: list[ast.AST] = []
    if len(node.args) >= 2:
        candidate_values.append(node.args[1])
    for keyword in node.keywords:
        if keyword.arg == "mode":
            candidate_values.append(keyword.value)
    for value in candidate_values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            if any(mode in value.value for mode in write_modes):
                return True
    return False


def _should_discover_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    parent_kind: str | None,
    module: str,
) -> bool:
    """PURPOSE check whether a function-like node should become a block
    DOMAIN  blueprint checks
    """
    # Exclude all dunder methods in classes
    if parent_kind == "class" and node.name.startswith("__") and node.name.endswith("__"):
        return False
    # Exclude trivial getters/setters in classes (less than 3 lines of actual code)
    if parent_kind == "class" and _is_trivial_method(node):
        return False
    # Exclude very small nested functions (less than 5 lines)
    if parent_kind == "function" and _is_tiny_nested_function(node):
        return False
    return True


def _derive_module_path(relative_path: Path) -> str:
    """PURPOSE derive module path from relative file path
    DOMAIN  blueprint checks
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
    """PURPOSE get and clean imports from Python code tree
        DOMAIN  blueprint checks

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
    source_text: str,
) -> Optional[DiscoveredCodeUnit]:
    """PURPOSE get class information from Python code node
        DOMAIN  blueprint checks

    """
    methods = _extract_direct_child_function_qualified_names(
        nodes=node.body,
        module=module,
        parent_symbol=symbol,
        skip_dunder=True,
    )
    functions = _extract_direct_child_class_qualified_names(
        nodes=node.body,
        module=module,
        parent_symbol=symbol,
    )

    # Extract decorators
    decorators = _extract_decorators(node.decorator_list)

    # Extract docstring
    docstring = ast.get_docstring(node)

    # Extract structured calls from this class
    calls = _extract_structured_calls_from_node(node)

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
        calls=calls,
        normalized_body_hash=_normalized_body_hash(node),
        dangerous_capabilities=_detect_dangerous_capabilities(node),
    )


def _extract_function_unit(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    file_path: str,
    module: str,
    imports: List[str],
    symbol: str,
    symbol_type: str,
    source_text: str,
) -> Optional[DiscoveredCodeUnit]:
    """PURPOSE get function information from Python code node
        DOMAIN  blueprint checks

    """
    # Extract decorators
    decorators = _extract_decorators(node.decorator_list)

    # Extract docstring
    docstring = ast.get_docstring(node)

    # Extract signature
    signature = _extract_function_signature(node)
    functions = _extract_direct_child_qualified_names(
        nodes=node.body,
        module=module,
        parent_symbol=symbol,
    )
    # Extract structured calls from this function
    calls = _extract_structured_calls_from_node(node)

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
        calls=calls,
        normalized_body_hash=_normalized_body_hash(node),
        dangerous_capabilities=_detect_dangerous_capabilities(node),
    )


def _extract_direct_child_symbols(nodes: List[ast.stmt], parent_symbol: str) -> List[str]:
    """PURPOSE get direct nested block symbols for a code unit
    DOMAIN  blueprint checks
    """

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


def _extract_direct_child_qualified_names(
    nodes: List[ast.stmt],
    module: str,
    parent_symbol: str,
) -> List[str]:
    """PURPOSE get direct nested block qualified names for a code unit
    DOMAIN  blueprint checks
    """

    child_qualified: List[str] = []
    child_qualified.extend(
        _extract_direct_child_function_qualified_names(
            nodes=nodes,
            module=module,
            parent_symbol=parent_symbol,
            skip_dunder=False,
        )
    )
    child_qualified.extend(
        _extract_direct_child_class_qualified_names(
            nodes=nodes,
            module=module,
            parent_symbol=parent_symbol,
        )
    )
    return child_qualified


def _extract_direct_child_function_qualified_names(
    nodes: List[ast.stmt],
    module: str,
    parent_symbol: str,
    skip_dunder: bool,
) -> List[str]:
    """PURPOSE get direct nested function-like qualified names for a code unit
    DOMAIN  blueprint checks
    """

    child_qualified: List[str] = []
    for node in nodes:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_") and not (
            node.name.startswith("__") and node.name.endswith("__")
        ):
            continue
        if skip_dunder and node.name.startswith("__") and node.name.endswith("__"):
            continue
        child_symbol = f"{parent_symbol}.{node.name}"
        child_qualified.append(f"{module}.{child_symbol}")
    return child_qualified


def _extract_direct_child_class_qualified_names(
    nodes: List[ast.stmt],
    module: str,
    parent_symbol: str,
) -> List[str]:
    """PURPOSE get direct nested class qualified names for a code unit
    DOMAIN  blueprint checks
    """

    child_qualified: List[str] = []
    for node in nodes:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            child_symbol = f"{parent_symbol}.{node.name}"
            child_qualified.append(f"{module}.{child_symbol}")
    return child_qualified


def _extract_direct_child_function_symbols(
    nodes: List[ast.stmt],
    parent_symbol: str,
    skip_dunder: bool,
) -> List[str]:
    """PURPOSE get direct nested function-like symbols for a code unit
    DOMAIN  blueprint checks
    """

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
    """PURPOSE get direct nested class symbols for a code unit
    DOMAIN  blueprint checks
    """

    child_symbols: List[str] = []
    for node in nodes:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            child_symbols.append(f"{parent_symbol}.{node.name}")
    return child_symbols


def _extract_decorators(decorator_list: List[ast.expr]) -> List[str]:
    """PURPOSE get decorator names from decorator list
    DOMAIN  blueprint checks
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
    """PURPOSE get dotted name from attribute node
    DOMAIN  blueprint checks
    """
    parts = []
    current = node

    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value

    if isinstance(current, ast.Name):
        parts.append(current.id)

    return ".".join(reversed(parts))


def _extract_structured_calls_from_node(
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
) -> List[Dict[str, Any]]:
    """PURPOSE get structured call references from an Python code node
        DOMAIN  blueprint checks

    """
    calls: List[Dict[str, Any]] = []

    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue

        call_info = _analyze_call(child.func)
        if call_info:
            calls.append(call_info)

    # Remove duplicates while preserving order
    unique_calls: List[Dict[str, Any]] = []
    seen = set()
    for call in calls:
        key = (call.get("context"), call.get("name"))
        if key not in seen:
            seen.add(key)
            unique_calls.append(call)

    return unique_calls


def _analyze_call(func_node: ast.expr) -> Dict[str, Any] | None:
    """PURPOSE analyze a call function node to extract context and name
    DOMAIN  blueprint checks
    """
    # Case 1: self.method_name() or cls.method_name()
    if isinstance(func_node, ast.Attribute):
        # Check if the object being accessed is 'self' or 'cls'
        if isinstance(func_node.value, ast.Name):
            if func_node.value.id in ("self", "cls"):
                return {"context": func_node.value.id, "name": func_node.attr}
        # Otherwise it's shard.get_blocks(), self.index.get_config(), etc.
        # These require runtime type info, so we only capture the tail name
        # but context will indicate it's not self/cls
        return {"context": _extract_context_prefix(func_node.value), "name": func_node.attr}

    # Case 2: bare_name() - could be function or class constructor
    if isinstance(func_node, ast.Name):
        return {"context": None, "name": func_node.id}

    # Case 3: Other complex expressions - ignore for dependency resolution
    return None


def _extract_context_prefix(node: ast.expr) -> str | None:
    """PURPOSE get context prefix from an attribute chain
    DOMAIN  blueprint checks
    """
    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):
        parts = [node.attr]
        current = node.value
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))

    return None


def _extract_function_signature(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Optional[str]:
    """PURPOSE get function signature as string
    DOMAIN  blueprint checks
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
    """PURPOSE get function arguments as string
    DOMAIN  blueprint checks
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
    """PURPOSE get return annotation from function node
    DOMAIN  blueprint checks
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
    """PURPOSE get type annotation from a parameter as string
    DOMAIN  blueprint checks
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
    """PURPOSE get the default value for a parameter as a Python literal
    DOMAIN  blueprint checks
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
    """PURPOSE convert a value written in source code to its Python value
    DOMAIN  blueprint checks
    """
    if node is None:
        return None
    if isinstance(node, ast.Constant):
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
    """PURPOSE get input/output metadata from a class or function node
        DOMAIN  blueprint checks

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
    """PURPOSE get input/output metadata from a function node
        DOMAIN  blueprint checks

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
    """PURPOSE build a mapping of parameter names to whether they have defaults
    DOMAIN  blueprint checks
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


def _is_data_class(node: ast.ClassDef) -> bool:
    """PURPOSE check if a class is a data class (no instance methods)
    DOMAIN  blueprint checks
    """
    # Count instance methods (excluding __init__ and __init_subclass__)
    instance_methods = 0
    for stmt in node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if stmt.name not in ("__init__", "__init_subclass__"):
                # Check if it's an instance method (not @staticmethod or @classmethod)
                is_static = any(
                    isinstance(d, ast.Name) and d.id == "staticmethod"
                    for d in stmt.decorator_list
                )
                is_class = any(
                    isinstance(d, ast.Name) and d.id == "classmethod"
                    for d in stmt.decorator_list
                )
                if not is_static and not is_class:
                    instance_methods += 1
    # If no instance methods, it's a data class
    return instance_methods == 0


def _is_protocol_or_abstract_class(node: ast.ClassDef) -> bool:
    """PURPOSE check if a class is a shape or abstract class
    DOMAIN  blueprint checks
    """
    # Check for @protocol decorator
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "protocol":
            return True
        # Handle typing.Protocol
        if isinstance(decorator, ast.Attribute) and decorator.attr == "Protocol":
            return True
    # Check for ABC base classes
    for base in node.bases:
        if isinstance(base, ast.Name):
            if base.id in ("ABC", "ABCMeta"):
                return True
        elif isinstance(base, ast.Attribute):
            # Check for abc.ABC, typing.Protocol, etc.
            attr_name = _get_attribute_name(base)
            if any(x in attr_name for x in ("ABC", "Protocol")):
                return True
    return False


def _is_decorator_nested_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    parent_kind: str | None,
    parent_symbols: List[str],
) -> bool:
    """PURPOSE check if this is a nested function inside a decorator factory
    DOMAIN  blueprint checks
    """
    if parent_kind != "function":
        return False
    # Check if parent function name suggests it's a decorator factory
    if parent_symbols:
        parent_name = parent_symbols[-1]
        return "decorator" in parent_name.lower()
    return False


def _is_schema_wrapper_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    module: str,
) -> bool:
    """PURPOSE check if a function is a schema.py wrapper function
    DOMAIN  blueprint checks
    """
    # Only check schema.py
    if module != "src.bpfw.core.catalog.schema":
        return False
    # If function body is just a return with .get() or dict access
    if len(node.body) == 1 and isinstance(node.body[0], ast.Return):
        return_expr = node.body[0].value
        # Check if it's a .get() call or direct dict access
        if isinstance(return_expr, ast.Call):
            if isinstance(return_expr.func, ast.Attribute):
                if return_expr.func.attr == "get":
                    return True
        elif isinstance(return_expr, ast.Attribute):
            # Direct attribute access like blueprint_data.blocks
            return True
    return False