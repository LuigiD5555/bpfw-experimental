"""Shared source-file repository for catalog scans and analyzers."""

import ast
from dataclasses import dataclass
from pathlib import Path

from bpfw.reports.finding import Finding


@dataclass(frozen=True)
class IndexedSourceNode:
    """Store an indexed AST node together with the source text that produced it."""

    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
    source_text: str


@dataclass(frozen=True)
class SourceFileSnapshot:
    """Store the parsed representation of one source file for one command run."""

    relative_path: str
    absolute_path: Path
    source_text: str
    syntax_tree: ast.Module
    imports: tuple[str, ...]
    module: str


class SourceFileRepository:
    """Load, parse, and index Python source files once per command execution.

    The repository acts as an identity map for parsed source files. Callers can
    share one instance across scanner and analyzers to avoid repeated reads,
    repeated AST parsing, and repeated symbol-index construction.
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize the source-file repository.

        Args:
            project_root: Project root used to resolve relative source paths.
        """
        self.project_root = project_root.resolve()
        self._snapshots_by_path: dict[str, SourceFileSnapshot | None] = {}
        self._findings_by_path: dict[str, list[Finding]] = {}
        self._node_index_by_path: dict[str, dict[str, IndexedSourceNode]] = {}

    def load_snapshot(self, absolute_path: Path, relative_path: Path) -> SourceFileSnapshot | None:
        """Load and parse one Python file, reusing an existing snapshot when available.

        Args:
            absolute_path: Absolute path to the Python file.
            relative_path: Path relative to the project root.

        Returns:
            Parsed source snapshot, or None when the file could not be read or parsed.
        """
        relative_key = relative_path.as_posix()
        if relative_key in self._snapshots_by_path:
            return self._snapshots_by_path[relative_key]

        try:
            source_text = absolute_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            self._store_failure(
                relative_key,
                Finding(
                    source="bpfw",
                    code="PYTHON_READ_ERROR",
                    severity="block",
                    message="Could not read file with UTF-8 encoding",
                    path=relative_key,
                ),
            )
            return None
        except OSError as error:
            self._store_failure(
                relative_key,
                Finding(
                    source="bpfw",
                    code="PYTHON_READ_ERROR",
                    severity="block",
                    message=f"Could not read Python file: {error}",
                    path=relative_key,
                ),
            )
            return None

        try:
            syntax_tree = ast.parse(source_text, filename=str(absolute_path))
        except SyntaxError as error:
            self._store_failure(
                relative_key,
                Finding(
                    source="bpfw",
                    code="PYTHON_PARSE_ERROR",
                    severity="block",
                    message="BPFW could not parse this Python file.",
                    path=relative_key,
                    evidence={
                        "line": error.lineno,
                        "offset": error.offset,
                    },
                ),
            )
            return None

        snapshot = SourceFileSnapshot(
            relative_path=relative_key,
            absolute_path=absolute_path,
            source_text=source_text,
            syntax_tree=syntax_tree,
            imports=tuple(_extract_imports(syntax_tree)),
            module=_derive_module_path(relative_path),
        )
        self._snapshots_by_path[relative_key] = snapshot
        self._findings_by_path[relative_key] = []
        return snapshot

    def get_snapshot(self, relative_path: str) -> SourceFileSnapshot | None:
        """Return a snapshot for a relative source path, loading it lazily if needed.

        Args:
            relative_path: Source path relative to the project root.

        Returns:
            Parsed source snapshot, or None when unavailable.
        """
        normalized_path = Path(relative_path)
        return self.load_snapshot(self.project_root / normalized_path, normalized_path)

    def get_findings(self, relative_path: Path | str) -> list[Finding]:
        """Return source load findings recorded for one relative path.

        Args:
            relative_path: Source path relative to the project root.

        Returns:
            Source file findings for the requested path.
        """
        relative_key = relative_path.as_posix() if isinstance(relative_path, Path) else str(relative_path)
        return list(self._findings_by_path.get(relative_key, []))

    def get_indexed_node(self, relative_path: str, symbol: str) -> IndexedSourceNode | None:
        """Return the indexed AST node for a symbol, loading the file lazily if needed.

        Args:
            relative_path: Source path relative to the project root.
            symbol: Dotted symbol name inside the file.

        Returns:
            Indexed source node, or None when the file or symbol is unavailable.
        """
        if relative_path not in self._node_index_by_path:
            self._node_index_by_path[relative_path] = self._build_node_index(relative_path)
        return self._node_index_by_path[relative_path].get(symbol)

    def _store_failure(self, relative_key: str, finding: Finding) -> None:
        """Store one source load failure.

        Args:
            relative_key: Relative source path key.
            finding: Finding describing the load failure.
        """
        self._snapshots_by_path[relative_key] = None
        self._findings_by_path[relative_key] = [finding]

    def _build_node_index(self, relative_path: str) -> dict[str, IndexedSourceNode]:
        """Build a symbol-to-node index for one Python source file.

        Args:
            relative_path: Source path relative to the project root.

        Returns:
            Mapping from dotted symbol name to indexed source node.
        """
        snapshot = self.get_snapshot(relative_path)
        if snapshot is None:
            return {}

        indexed_nodes: dict[str, IndexedSourceNode] = {}

        def visit_child_nodes(nodes: list[ast.stmt], parent_symbols: list[str]) -> None:
            """Visit class and function nodes and store them by dotted symbol."""
            for node in nodes:
                if isinstance(node, ast.ClassDef):
                    symbol = ".".join(parent_symbols + [node.name])
                    indexed_nodes[symbol] = IndexedSourceNode(node=node, source_text=snapshot.source_text)
                    visit_child_nodes(node.body, parent_symbols + [node.name])
                    continue
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbol = ".".join(parent_symbols + [node.name])
                    indexed_nodes[symbol] = IndexedSourceNode(node=node, source_text=snapshot.source_text)
                    visit_child_nodes(node.body, parent_symbols + [node.name])

        visit_child_nodes(snapshot.syntax_tree.body, [])
        return indexed_nodes


def _derive_module_path(relative_path: Path) -> str:
    """Derive a dotted module path from a relative Python file path.

    Args:
        relative_path: Path relative to the project root.

    Returns:
        Dotted module path.
    """
    parent_parts = list(relative_path.parent.parts)
    if parent_parts:
        return ".".join(parent_parts + [relative_path.stem])
    return relative_path.stem


def _extract_imports(tree: ast.AST) -> list[str]:
    """Extract import references from a parsed Python module.

    Args:
        tree: Parsed Python module tree.

    Returns:
        Imported module and symbol references.
    """
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
            continue
        if isinstance(node, ast.ImportFrom):
            module = node.module if node.module else ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                if module:
                    imports.append(f"{module}.{alias.name}")
                else:
                    imports.append(alias.name)
    return imports
