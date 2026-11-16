"""In-memory Python code tree cache for inspector sessions."""

import ast
from pathlib import Path


class InspectorAstCache:
    """Cache parsed Python code trees during a single inspector session."""

    def __init__(self) -> None:
        """Initialize an empty Python code tree cache."""
        self._modules_by_path: dict[Path, ast.Module] = {}

    def get_module(self, source_path: Path) -> ast.Module:
        """Get the parsed Python code tree for a source path."""
        normalized_path = source_path.resolve()
        cached_module = self._modules_by_path.get(normalized_path)
        if cached_module is not None:
            return cached_module

        source_text = normalized_path.read_text(encoding="utf-8")
        parsed_module = ast.parse(source_text, filename=str(normalized_path))
        self._modules_by_path[normalized_path] = parsed_module
        return parsed_module

    def clear(self) -> None:
        """Clear all cached Python code trees."""
        self._modules_by_path.clear()