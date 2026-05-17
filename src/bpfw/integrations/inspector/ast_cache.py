"""In-memory AST module cache for inspector sessions."""

import ast
from pathlib import Path


class InspectorAstCache:
    """Cache parsed AST modules during a single inspector session."""

    def __init__(self) -> None:
        """Initialize an empty AST cache."""
        self._modules_by_path: dict[Path, ast.Module] = {}

    def get_module(self, source_path: Path) -> ast.Module:
        """Return the parsed AST module for a source path.

        Args:
            source_path: Path to the source file.

        Returns:
            Parsed AST module, parsed from cache or fresh if not cached.

        Raises:
            OSError: If the source file cannot be read.
            SyntaxError: If the source file has invalid Python syntax.
        """
        normalized_path = source_path.resolve()
        cached_module = self._modules_by_path.get(normalized_path)
        if cached_module is not None:
            return cached_module

        source_text = normalized_path.read_text(encoding="utf-8")
        parsed_module = ast.parse(source_text, filename=str(normalized_path))
        self._modules_by_path[normalized_path] = parsed_module
        return parsed_module

    def clear(self) -> None:
        """Clear all cached AST modules."""
        self._modules_by_path.clear()