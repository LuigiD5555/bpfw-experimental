"""PURPOSE in-memory Python code tree cache for inspector sessions
DOMAIN  inspector workflow
"""

import ast
from pathlib import Path


class InspectorAstCache:
    """PURPOSE cache parsed Python code trees during a single inspector session
        DOMAIN  inspector workflow

    """

    def __init__(self) -> None:
        """PURPOSE set up an empty Python code tree cache
                DOMAIN  inspector workflow

        """
        self._modules_by_path: dict[Path, ast.Module] = {}

    def get_module(self, source_path: Path) -> ast.Module:
        """PURPOSE get the parsed Python code tree for a source path
                DOMAIN  inspector workflow

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
        """PURPOSE clear all cached Python code trees
                DOMAIN  inspector workflow

        """
        self._modules_by_path.clear()