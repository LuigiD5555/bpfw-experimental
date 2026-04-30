from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


_IGNORED_ROOTS = {".git", ".venv", "__pycache__", ".bpfw", "dist", "build"}
_LAYER_HINTS = ("domain", "application", "infrastructure", "public")
_ENTRYPOINT_HINTS = {"public", "api", "cli", "routes", "views"}


@dataclass(slots=True)
class DiscoveredSymbol:
    """Represents a Python symbol discovered during mechanical scanning."""

    name: str
    kind: str
    file_path: str
    parent_name: str | None
    public_methods: list[str]


@dataclass(slots=True)
class DiscoveredImport:
    """Represents an import discovered during mechanical scanning."""

    file_path: str
    imported_module: str
    imported_name: str | None


@dataclass(slots=True)
class MechanicalScanResult:
    """Contains all mechanically discovered project facts."""

    files: list[str]
    symbols: list[DiscoveredSymbol]
    imports: list[DiscoveredImport]
    probable_layers: dict[str, str]
    probable_entrypoints: list[str]


class MechanicalProjectScanner:
    """Scans a Python project without using AI or semantic inference."""

    def scan(self, project_root: Path) -> MechanicalScanResult:
        """Scan files, symbols, imports, layers, and probable entrypoints."""
        discovered_files: list[str] = []
        discovered_symbols: list[DiscoveredSymbol] = []
        discovered_imports: list[DiscoveredImport] = []
        probable_layers: dict[str, str] = {}
        probable_entrypoints: list[str] = []

        for python_file_path in sorted(project_root.rglob("*.py")):
            if any(part in _IGNORED_ROOTS for part in python_file_path.parts):
                continue

            relative_file_path = python_file_path.relative_to(project_root).as_posix()
            discovered_files.append(relative_file_path)

            probable_layer = self._infer_layer(relative_file_path)
            if probable_layer:
                probable_layers[relative_file_path] = probable_layer

            if self._is_entrypoint_path(relative_file_path):
                probable_entrypoints.append(relative_file_path)

            try:
                module_tree = ast.parse(python_file_path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue

            discovered_symbols.extend(self._extract_symbols(relative_file_path=relative_file_path, module_tree=module_tree))
            discovered_imports.extend(self._extract_imports(relative_file_path=relative_file_path, module_tree=module_tree))

        return MechanicalScanResult(
            files=discovered_files,
            symbols=discovered_symbols,
            imports=discovered_imports,
            probable_layers=probable_layers,
            probable_entrypoints=sorted(probable_entrypoints),
        )

    def _extract_symbols(self, relative_file_path: str, module_tree: ast.Module) -> list[DiscoveredSymbol]:
        symbols: list[DiscoveredSymbol] = []
        for node in module_tree.body:
            if isinstance(node, ast.ClassDef):
                public_methods = [
                    method.name
                    for method in node.body
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and not method.name.startswith("_")
                ]
                symbols.append(
                    DiscoveredSymbol(
                        name=node.name,
                        kind="class",
                        file_path=relative_file_path,
                        parent_name=None,
                        public_methods=public_methods,
                    )
                )
                for method_name in public_methods:
                    symbols.append(
                        DiscoveredSymbol(
                            name=f"{node.name}.{method_name}",
                            kind="method",
                            file_path=relative_file_path,
                            parent_name=node.name,
                            public_methods=[],
                        )
                    )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(
                    DiscoveredSymbol(
                        name=node.name,
                        kind="function",
                        file_path=relative_file_path,
                        parent_name=None,
                        public_methods=[],
                    )
                )
        return symbols

    def _extract_imports(self, relative_file_path: str, module_tree: ast.Module) -> list[DiscoveredImport]:
        imports: list[DiscoveredImport] = []
        for node in ast.walk(module_tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(
                        DiscoveredImport(
                            file_path=relative_file_path,
                            imported_module=alias.name,
                            imported_name=None,
                        )
                    )
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                for alias in node.names:
                    imports.append(
                        DiscoveredImport(
                            file_path=relative_file_path,
                            imported_module=module_name,
                            imported_name=alias.name,
                        )
                    )
        return imports

    def _infer_layer(self, relative_file_path: str) -> str:
        path_parts = Path(relative_file_path).parts
        for part in path_parts:
            if part in _LAYER_HINTS:
                return part
        return ""

    def _is_entrypoint_path(self, relative_file_path: str) -> bool:
        path_parts = set(Path(relative_file_path).parts)
        return bool(path_parts.intersection(_ENTRYPOINT_HINTS))
