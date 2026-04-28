"""AST-based scanner for symbols that may duplicate responsibility intent."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class ScannedSymbol:
    """Symbol discovered from Python source files."""

    symbol_name: str
    symbol_type: str
    qualified_name: str
    file_path: str
    line_number: int


@dataclass(slots=True)
class SymbolScanIssue:
    """Scanner warning or block issue."""

    severity: str
    code: str
    message: str
    file_path: str
    recommendation: str


@dataclass(slots=True)
class SymbolScanResult:
    """Collected symbols and scanner-level issues."""

    symbols: list[ScannedSymbol] = field(default_factory=list)
    issues: list[SymbolScanIssue] = field(default_factory=list)


class _SymbolVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str) -> None:
        self._relative_path = relative_path
        self._current_classes: list[str] = []
        self.symbols: list[ScannedSymbol] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        class_qualified_name = ".".join([*self._current_classes, node.name])
        self.symbols.append(
            ScannedSymbol(
                symbol_name=node.name,
                symbol_type="class",
                qualified_name=class_qualified_name,
                file_path=self._relative_path,
                line_number=node.lineno,
            )
        )
        self._current_classes.append(node.name)
        self.generic_visit(node)
        self._current_classes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._append_function_symbol(node_name=node.name, line_number=node.lineno)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._append_function_symbol(node_name=node.name, line_number=node.lineno)
        self.generic_visit(node)

    def _append_function_symbol(self, node_name: str, line_number: int) -> None:
        if self._current_classes:
            qualified_name = ".".join([*self._current_classes, node_name])
            symbol_type = "method"
        else:
            qualified_name = node_name
            symbol_type = "function"

        self.symbols.append(
            ScannedSymbol(
                symbol_name=node_name,
                symbol_type=symbol_type,
                qualified_name=qualified_name,
                file_path=self._relative_path,
                line_number=line_number,
            )
        )


def _collect_python_files(project_root: Path) -> list[Path]:
    source_root = project_root / "src"
    if not source_root.exists():
        return []

    files: list[Path] = []
    for python_file in source_root.rglob("*.py"):
        relative_path = python_file.resolve().relative_to(project_root.resolve())
        if relative_path.parts[:2] == ("src", "bpfw"):
            continue
        files.append(python_file)
    return sorted(files)


def scan_project_symbols(project_root: Path) -> SymbolScanResult:
    """Scan classes, functions, and methods from project Python files."""

    issues: list[SymbolScanIssue] = []
    symbols: list[ScannedSymbol] = []

    for file_path in _collect_python_files(project_root=project_root):
        relative_file_path = str(file_path.resolve().relative_to(project_root.resolve()))
        try:
            parsed_tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=relative_file_path)
        except SyntaxError as error:
            issues.append(
                SymbolScanIssue(
                    severity="warning",
                    code="DP001",
                    message=f"Cannot parse file for duplication scan: {error.msg}",
                    file_path=relative_file_path,
                    recommendation="Fix syntax errors to enable duplication detection",
                )
            )
            continue
        except OSError as error:
            issues.append(
                SymbolScanIssue(
                    severity="warning",
                    code="DP002",
                    message=f"Cannot read file for duplication scan: {error}",
                    file_path=relative_file_path,
                    recommendation="Ensure files are readable for duplication detection",
                )
            )
            continue

        visitor = _SymbolVisitor(relative_path=relative_file_path)
        visitor.visit(parsed_tree)
        symbols.extend(visitor.symbols)

    return SymbolScanResult(symbols=symbols, issues=issues)
