"""Central registry and file discovery boundary for source languages.

Alpha.8 intentionally registers only Python. Later dialect adapters extend this registry
without adding hard-coded suffix scans to catalog, cache, planner, drift, or watch code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


@dataclass(frozen=True, slots=True)
class LanguageDefinition:
    """Describe one registered source language without exposing parser-native nodes."""

    identifier: str
    suffixes: frozenset[str]

    def __post_init__(self) -> None:
        if not self.identifier or self.identifier != self.identifier.lower():
            raise ValueError("Language identifiers must be non-empty lowercase strings")
        if not self.suffixes or any(not suffix.startswith(".") for suffix in self.suffixes):
            raise ValueError("Language suffixes must be non-empty dot-prefixed strings")


class SourceLanguageRegistry:
    """Resolve source suffixes through one immutable-by-convention registry."""

    def __init__(self, definitions: Iterable[LanguageDefinition]) -> None:
        by_identifier: dict[str, LanguageDefinition] = {}
        by_suffix: dict[str, LanguageDefinition] = {}
        for definition in definitions:
            if definition.identifier in by_identifier:
                raise ValueError(f"Duplicate language identifier: {definition.identifier}")
            by_identifier[definition.identifier] = definition
            for suffix in definition.suffixes:
                normalized_suffix = suffix.lower()
                if normalized_suffix in by_suffix:
                    raise ValueError(f"Source suffix already registered: {suffix}")
                by_suffix[normalized_suffix] = definition
        self._by_identifier = by_identifier
        self._by_suffix = by_suffix

    @property
    def source_suffixes(self) -> frozenset[str]:
        """Return every suffix recognized as source code."""

        return frozenset(self._by_suffix)

    def language_for_path(self, path: Path) -> LanguageDefinition | None:
        """Return the registered language for a path, if any."""

        return self._by_suffix.get(path.suffix.lower())


default_language_registry = SourceLanguageRegistry(
    [
        LanguageDefinition(identifier="python", suffixes=frozenset({".py"})),
        LanguageDefinition(identifier="go", suffixes=frozenset({".go"})),
        LanguageDefinition(identifier="rust", suffixes=frozenset({".rs"})),
        LanguageDefinition(identifier="html", suffixes=frozenset({".html", ".htm"})),
        LanguageDefinition(identifier="css", suffixes=frozenset({".css"})),
    ]
)


DEFAULT_IGNORED_DIRECTORIES = [
    ".git", ".bpfw", ".venv", "venv", "__pycache__", "node_modules",
    "tests", "migrations", "target", "vendor", "build", "dist",
]


def detect_source_roots(project_root: Path) -> list[str]:
    """Choose safe initial roots for Python and mixed-language repositories."""

    resolved_root = project_root.resolve()
    if (resolved_root / "go.mod").is_file() or (resolved_root / "Cargo.toml").is_file():
        return ["."]
    common_roots = [
        name for name in ("src", "app", "lib", "core", "cmd", "internal", "pkg", "web", "static")
        if (resolved_root / name).is_dir()
    ]
    if common_roots:
        return common_roots
    if any(
        child.is_file() and default_language_registry.language_for_path(child) is not None
        for child in resolved_root.iterdir()
    ):
        return ["."]
    return ["src", "app"]


def is_path_ignored(file_path: Path, ignored_paths: Iterable[str]) -> bool:
    """Return whether an ignored component occurs in a project-relative path."""

    ignored = frozenset(ignored_paths)
    return any(part in ignored for part in file_path.parts)


def iter_source_files(
    project_root: Path,
    source_roots: Iterable[str],
    ignored_paths: Iterable[str],
    *,
    language: str | None = None,
    registry: SourceLanguageRegistry = default_language_registry,
) -> Iterator[tuple[Path, Path, LanguageDefinition]]:
    """Yield absolute path, project-relative path, and language in stable order."""

    resolved_root = project_root.resolve()
    candidates: list[tuple[Path, Path, LanguageDefinition]] = []
    for source_root in source_roots:
        root = resolved_root / source_root
        if not root.is_dir():
            continue
        for absolute_path in root.rglob("*"):
            if not absolute_path.is_file():
                continue
            definition = registry.language_for_path(absolute_path)
            if definition is None or (language is not None and definition.identifier != language):
                continue
            try:
                relative_path = absolute_path.relative_to(resolved_root)
            except ValueError:
                continue
            if is_path_ignored(relative_path, ignored_paths):
                continue
            candidates.append((absolute_path, relative_path, definition))
    yield from sorted(candidates, key=lambda item: item[1].as_posix())
