"""Deterministic code-duplication analysis for catalog verification."""

import ast
import copy
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from bpfw.core.catalog.models import DiscoveredCodeUnit
from bpfw.core.catalog.source_repository import SourceFileRepository
from bpfw.reports.finding import FINDING_SEVERITY_WARNING, Finding

_SOURCE = "bpfw"
_CODE_CLONE = "NORMALIZED_AST_CLONE"
_WRAPPER = "TRIVIAL_WRAPPER"
_SAME_RETURN = "SAME_RETURN_EXPRESSION"
_FUNCTION_TYPES = {"function", "method", "nested_function"}


@dataclass(frozen=True)
class _IndexedNode:
    """Store an AST node together with its source text."""

    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
    source_text: str


@dataclass(frozen=True)
class _AnalyzedUnit:
    """Store deterministic duplicate-analysis facts for one code unit."""

    unit: DiscoveredCodeUnit
    body_hash: str
    return_hash: str | None
    wrapper_target: str | None
    wrapper_arguments: tuple[str, ...]
    call_names: tuple[str, ...]
    single_constant_return: bool


class _LocalNameNormalizer(ast.NodeTransformer):
    """Normalize function-local variable names while keeping external names stable."""

    def __init__(self, argument_names: Iterable[str]) -> None:
        """Initialize the local-name normalizer.

        Args:
            argument_names: Function argument names that should be mapped to stable argN names.
        """
        self._name_map: dict[str, str] = {}
        self._next_local_index = 0
        for index, argument_name in enumerate(argument_names):
            self._name_map[argument_name] = f"arg{index}"

    def visit_arg(self, node: ast.arg) -> ast.arg:
        """Normalize a function argument name."""
        node.arg = self._name_map.get(node.arg, node.arg)
        return node

    def visit_Name(self, node: ast.Name) -> ast.AST:
        """Normalize only local variables and arguments."""
        if isinstance(node.ctx, ast.Store):
            node.id = self._mapped_local_name(node.id)
            return node
        if node.id in self._name_map:
            node.id = self._name_map[node.id]
        return node

    def _mapped_local_name(self, name: str) -> str:
        """Return a stable local name for an original local variable name."""
        if name not in self._name_map:
            self._name_map[name] = f"local{self._next_local_index}"
            self._next_local_index += 1
        return self._name_map[name]


class CodeDuplicateAnalyzer:
    """Analyze real Python code duplication without using declared purposes."""

    def __init__(
        self,
        project_root: Path,
        discovered_units: list[DiscoveredCodeUnit],
        source_repository: SourceFileRepository | None = None,
    ) -> None:
        """Initialize the analyzer.

        Args:
            project_root: Project root containing source files.
            discovered_units: Code units discovered by the catalog scanner.
            source_repository: Optional shared source repository for parsed files.
        """
        self.project_root = project_root
        self.discovered_units = discovered_units
        self.source_repository = source_repository or SourceFileRepository(project_root)

    def analyze(self) -> list[Finding]:
        """Detect code clones, repeated returns, and trivial wrappers."""
        analyzed_units = self._analyze_units()
        findings: list[Finding] = []
        findings.extend(self._find_normalized_ast_clones(analyzed_units))
        findings.extend(self._find_same_return_expressions(analyzed_units))
        findings.extend(self._find_trivial_wrappers(analyzed_units))
        return findings

    def _analyze_units(self) -> list[_AnalyzedUnit]:
        """Build deterministic facts for discovered function-like units."""
        analyzed_units: list[_AnalyzedUnit] = []
        for unit in self.discovered_units:
            if unit.symbol_type not in _FUNCTION_TYPES:
                continue
            indexed_node = self._indexed_node_for_unit(unit)
            if indexed_node is None:
                continue
            node = indexed_node.node
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body_without_docstring = _body_without_docstring(node.body)
            if not body_without_docstring:
                continue
            body_hash = _normalized_body_hash(node, include_function_signature=False)
            return_hash = _single_return_expression_hash(node)
            wrapper_target, wrapper_arguments = _trivial_wrapper_target(node)
            call_names = tuple(sorted(_call_names(node)))
            single_constant_return = _is_single_constant_return(node)
            analyzed_units.append(
                _AnalyzedUnit(
                    unit=unit,
                    body_hash=body_hash,
                    return_hash=return_hash,
                    wrapper_target=wrapper_target,
                    wrapper_arguments=wrapper_arguments,
                    call_names=call_names,
                    single_constant_return=single_constant_return,
                )
            )
        return analyzed_units

    def _find_normalized_ast_clones(self, analyzed_units: list[_AnalyzedUnit]) -> list[Finding]:
        """Find function-like units with the same normalized AST body."""
        grouped_units: dict[str, list[_AnalyzedUnit]] = {}
        for analyzed_unit in analyzed_units:
            grouped_units.setdefault(analyzed_unit.body_hash, []).append(analyzed_unit)

        findings: list[Finding] = []
        for body_hash, group in grouped_units.items():
            if len(group) < 2:
                continue
            if self._all_units_are_methods_on_related_operation_types(group):
                continue
            if all(item.single_constant_return for item in group):
                continue
            findings.append(
                Finding(
                    source=_SOURCE,
                    code=_CODE_CLONE,
                    severity=FINDING_SEVERITY_WARNING,
                    path=group[0].unit.path,
                    symbol=group[0].unit.symbol,
                    message="More than one code block has the same normalized AST body.",
                    evidence={
                        "body_hash": body_hash,
                        "units": [_unit_label(item.unit) for item in group],
                        "calls": sorted(set().union(*(set(item.call_names) for item in group))),
                    },
                )
            )
        return findings

    def _find_same_return_expressions(self, analyzed_units: list[_AnalyzedUnit]) -> list[Finding]:
        """Find units that return the same normalized expression."""
        grouped_units: dict[str, list[_AnalyzedUnit]] = {}
        for analyzed_unit in analyzed_units:
            if analyzed_unit.return_hash is None:
                continue
            grouped_units.setdefault(analyzed_unit.return_hash, []).append(analyzed_unit)

        findings: list[Finding] = []
        for return_hash, group in grouped_units.items():
            if len(group) < 2:
                continue
            if all(item.body_hash == group[0].body_hash for item in group):
                continue
            findings.append(
                Finding(
                    source=_SOURCE,
                    code=_SAME_RETURN,
                    severity=FINDING_SEVERITY_WARNING,
                    path=group[0].unit.path,
                    symbol=group[0].unit.symbol,
                    message="More than one code block returns the same normalized expression.",
                    evidence={
                        "return_hash": return_hash,
                        "units": [_unit_label(item.unit) for item in group],
                    },
                )
            )
        return findings

    def _find_trivial_wrappers(self, analyzed_units: list[_AnalyzedUnit]) -> list[Finding]:
        """Find units that only delegate to another callable without adding behavior."""
        findings: list[Finding] = []
        for analyzed_unit in analyzed_units:
            if analyzed_unit.wrapper_target is None:
                continue
            unit = analyzed_unit.unit
            findings.append(
                Finding(
                    source=_SOURCE,
                    code=_WRAPPER,
                    severity=FINDING_SEVERITY_WARNING,
                    path=unit.path,
                    symbol=unit.symbol,
                    message="This code block only delegates to another callable.",
                    evidence={
                        "unit": _unit_label(unit),
                        "target": analyzed_unit.wrapper_target,
                        "passed_arguments": list(analyzed_unit.wrapper_arguments),
                    },
                )
            )
        return findings

    def _indexed_node_for_unit(self, unit: DiscoveredCodeUnit) -> _IndexedNode | None:
        """Return the AST node that corresponds to a discovered code unit."""
        return self.source_repository.get_indexed_node(unit.path, unit.symbol)

    def _build_node_index(self, relative_path: str) -> dict[str, _IndexedNode]:
        """Build a symbol-to-node index for one Python file."""
        source_path = self.project_root / relative_path
        try:
            source_text = source_path.read_text(encoding="utf-8")
            tree = ast.parse(source_text, filename=str(source_path))
        except (FileNotFoundError, UnicodeDecodeError, SyntaxError):
            return {}

        indexed_nodes: dict[str, _IndexedNode] = {}

        def visit_child_nodes(nodes: list[ast.stmt], parent_symbols: list[str]) -> None:
            for node in nodes:
                if isinstance(node, ast.ClassDef):
                    symbol = ".".join(parent_symbols + [node.name])
                    indexed_nodes[symbol] = _IndexedNode(node=node, source_text=source_text)
                    visit_child_nodes(node.body, parent_symbols + [node.name])
                    continue
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbol = ".".join(parent_symbols + [node.name])
                    indexed_nodes[symbol] = _IndexedNode(node=node, source_text=source_text)
                    visit_child_nodes(node.body, parent_symbols + [node.name])

        visit_child_nodes(tree.body, [])
        return indexed_nodes

    def _all_units_are_methods_on_related_operation_types(self, group: list[_AnalyzedUnit]) -> bool:
        """Return whether a clone group is only repeated interface plumbing on operation classes."""
        method_names = {_last_symbol_part(item.unit.symbol) for item in group}
        if len(method_names) != 1:
            return False
        method_name = next(iter(method_names))
        if method_name not in {"affected_files", "validate", "is_empty"}:
            return False
        parent_names = {_parent_symbol_part(item.unit.symbol) for item in group}
        return all(parent.endswith("Operation") or parent.endswith("Plan") for parent in parent_names)


def _body_without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    """Return a function or class body without its leading docstring."""
    if not body:
        return []
    first_statement = body[0]
    if isinstance(first_statement, ast.Expr):
        value = first_statement.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return body[1:]
    return body


def _normalized_body_hash(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    include_function_signature: bool,
) -> str:
    """Return a hash for a normalized function body without reparsing source text."""
    argument_names = [argument.arg for argument in node.args.args]
    copied_node = copy.deepcopy(node)
    copied_node.name = "function"
    if not include_function_signature:
        copied_node.returns = None
        copied_node.decorator_list = []
    copied_node.body = _body_without_docstring(copied_node.body)
    normalizer = _LocalNameNormalizer(argument_names)
    normalized_node = normalizer.visit(copied_node)
    ast.fix_missing_locations(normalized_node)
    normalized_dump = ast.dump(normalized_node, include_attributes=False)
    return hashlib.sha256(normalized_dump.encode("utf-8")).hexdigest()


def _is_single_constant_return(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return whether a function only returns one literal constant."""
    body = _body_without_docstring(node.body)
    if len(body) != 1:
        return False
    statement = body[0]
    if not isinstance(statement, ast.Return):
        return False
    return isinstance(statement.value, ast.Constant)


def _single_return_expression_hash(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Return a hash when a function has a single return expression."""
    body = _body_without_docstring(node.body)
    if len(body) != 1:
        return None
    statement = body[0]
    if not isinstance(statement, ast.Return) or statement.value is None:
        return None
    normalized_expression = _normalized_expression(statement.value, [arg.arg for arg in node.args.args])
    return hashlib.sha256(normalized_expression.encode("utf-8")).hexdigest()


def _normalized_expression(expression: ast.expr, argument_names: list[str]) -> str:
    """Return a normalized dump for one expression."""
    expression_wrapper = ast.Expression(body=expression)
    normalizer = _LocalNameNormalizer(argument_names)
    normalized_expression = normalizer.visit(expression_wrapper)
    ast.fix_missing_locations(normalized_expression)
    return ast.dump(normalized_expression, include_attributes=False)


def _trivial_wrapper_target(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str | None, tuple[str, ...]]:
    """Return wrapper target information when a function only delegates."""
    body = _body_without_docstring(node.body)
    if len(body) != 1:
        return None, ()
    statement = body[0]
    if not isinstance(statement, ast.Return):
        return None, ()
    if not isinstance(statement.value, ast.Call):
        return None, ()

    call = statement.value
    target = _call_name(call.func)
    if target is None:
        return None, ()
    argument_names = [argument.arg for argument in node.args.args]
    if argument_names and argument_names[0] in {"self", "cls"}:
        comparable_arguments = argument_names[1:]
    else:
        comparable_arguments = argument_names
    if not comparable_arguments:
        return None, ()
    if target in {"bool", "dict", "float", "frozenset", "int", "list", "set", "str", "tuple"}:
        return None, ()
    passed_arguments = _passed_argument_names(call)
    if tuple(comparable_arguments) != passed_arguments:
        return None, ()
    if call.keywords:
        return None, ()
    return target, passed_arguments


def _passed_argument_names(call: ast.Call) -> tuple[str, ...]:
    """Return positional argument names passed to a call."""
    names: list[str] = []
    for argument in call.args:
        if not isinstance(argument, ast.Name):
            return ()
        names.append(argument.id)
    return tuple(names)


def _call_names(node: ast.AST) -> set[str]:
    """Return all call names used by an AST node."""
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        call_name = _call_name(child.func)
        if call_name is not None:
            names.add(call_name)
    return names


def _call_name(node: ast.AST) -> str | None:
    """Return a dotted call name from a call target."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent_name = _call_name(node.value)
        if parent_name is None:
            return node.attr
        return f"{parent_name}.{node.attr}"
    return None


def _unit_label(unit: DiscoveredCodeUnit) -> str:
    """Return a stable label for a discovered code unit."""
    return f"{unit.path}::{unit.symbol}"


def _last_symbol_part(symbol: str) -> str:
    """Return the last part of a dotted symbol."""
    return symbol.split(".")[-1]


def _parent_symbol_part(symbol: str) -> str:
    """Return the parent part of a dotted symbol."""
    parts = symbol.split(".")
    if len(parts) < 2:
        return ""
    return parts[-2]
