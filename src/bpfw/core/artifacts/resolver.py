"""Resolve code, prompts, configuration, specs, and generic files to source spans."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import tomllib
from pathlib import Path
from typing import Any

import yaml

from bpfw.core.artifacts.models import ResolvedArtifact
from bpfw.core.catalog.models import DiscoveredCodeUnit
from bpfw.core.catalog.source_repository import SourceFileRepository

_PROMPT_SUFFIXES = {".prompt", ".md", ".txt", ".tmpl", ".tpl"}
_CONFIG_SUFFIXES = {".yaml", ".yml", ".json", ".toml"}
_VAR_PATTERNS = [
    re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*\}\}"),
    re.compile(r"\$\{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*\}"),
]
_REGION_START = re.compile(r"<!--\s*bpfw:start\s+([^\s>]+)\s*-->", re.I)
_REGION_END = re.compile(r"<!--\s*bpfw:end\s+([^\s>]+)\s*-->", re.I)


def _clean(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def block_artifacts(block: dict[str, Any]) -> list[dict[str, Any]]:
    """Return v2 artifacts plus a synthetic legacy code artifact."""
    runtime_values = block.get("__bpfw_effective_artifacts")
    source_values = runtime_values if isinstance(runtime_values, list) else block.get("artifacts", [])
    values = [dict(item) for item in source_values if isinstance(item, dict)]
    code = block.get("code")
    logical_kind = (_clean(block.get("kind")) or "code").lower()
    code_kind = (_clean(code.get("kind")) or "").lower() if isinstance(code, dict) else ""
    legacy_is_physical = logical_kind == "code" or code_kind not in {"concept", "subsystem", "flow", "logical"}
    if isinstance(code, dict) and _clean(code.get("path")) and legacy_is_physical:
        legacy = {
            "id": "legacy_code",
            "uid": code.get("uid"),
            "type": "code",
            "path": code.get("path"),
            "language": code.get("language"),
            "symbol": code.get("symbol"),
            "kind": code.get("kind"),
            "role": "legacy_code_location",
            "primary": not bool(values),
            "start_line": code.get("start_line"),
            "end_line": code.get("end_line"),
        }
        if not any(
            item.get("type", "code") == "code"
            and item.get("path") == legacy["path"]
            and item.get("symbol") == legacy["symbol"]
            for item in values
        ):
            values.insert(0, legacy)
    return values


def choose_primary_artifact(block: dict[str, Any]) -> dict[str, Any] | None:
    values = block_artifacts(block)
    if not values:
        return None
    explicit = next((item for item in values if item.get("primary") is True), None)
    if explicit:
        return explicit
    priorities = {"implementation": 0, "behavior_contract": 1, "constraint": 2, "verification": 3}
    return sorted(values, key=lambda item: (priorities.get(str(item.get("role") or ""), 10), values.index(item)))[0]


class ArtifactResolver:
    """Parser-neutral source locator used by Inspector, history, and verification."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self._cache: dict[str, ResolvedArtifact] = {}
        self._source_repository = SourceFileRepository(self.project_root)
        self._file_contents: dict[Path, tuple[str, str, list[str]]] = {}
        self._language_units: dict[tuple[str, str], list[DiscoveredCodeUnit]] = {}
        self._python_candidates: dict[str, dict[str, list[tuple[ast.AST, str]]]] = {}

    def resolve(self, artifact: dict[str, Any]) -> ResolvedArtifact:
        cache_key = json.dumps(artifact, sort_keys=True, default=str)
        if cache_key in self._cache:
            return self._cache[cache_key]
        result = self._resolve(artifact)
        self._cache[cache_key] = result
        return result

    def _resolve(self, artifact: dict[str, Any]) -> ResolvedArtifact:
        relative = _clean(artifact.get("path")) or ""
        atype = (_clean(artifact.get("type")) or "code").lower()
        path = self.project_root / relative
        base = ResolvedArtifact(
            artifact_id=_clean(artifact.get("id")) or _clean(artifact.get("symbol")) or relative or "artifact",
            artifact_uid=_clean(artifact.get("uid")), type=atype, path=relative,
            language=_clean(artifact.get("language")), format=_clean(artifact.get("format")),
            symbol=_clean(artifact.get("symbol")), kind=_clean(artifact.get("kind")), role=_clean(artifact.get("role")),
        )
        if not relative or (path not in self._file_contents and not path.is_file()):
            base.message = f"Artifact file not found: {relative}" if relative else "Artifact path is missing."
            return base
        try:
            if path not in self._file_contents:
                data = path.read_bytes()
                text = data.decode("utf-8", errors="replace")
                self._file_contents[path] = (text, hashlib.sha256(data).hexdigest(), text.splitlines(keepends=True))
            text, content_hash, lines = self._file_contents[path]
        except OSError as exc:
            base.message = str(exc)
            return base
        base.content_hash = content_hash
        suffix = path.suffix.lower()
        if atype == "code":
            resolved = self._resolve_code(base, artifact, path, text)
        elif atype in {"prompt", "spec", "skill", "documentation", "markdown"} or suffix in _PROMPT_SUFFIXES:
            resolved = self._resolve_textual(base, artifact, text)
        elif atype in {"config", "configuration", "schema"} or suffix in _CONFIG_SUFFIXES:
            resolved = self._resolve_config(base, artifact, text, suffix)
        else:
            resolved = self._whole_file(base, text, parser="text")
        if resolved.resolved:
            start = max(1, int(resolved.start_line or 1))
            end = max(start, int(resolved.end_line or start))
            segment = "".join(lines[start - 1:end])
            resolved.content_hash = hashlib.sha256(segment.encode("utf-8")).hexdigest()
        return resolved

    def _resolve_code(self, base: ResolvedArtifact, artifact: dict[str, Any], path: Path, text: str) -> ResolvedArtifact:
        language = base.language
        if not language:
            language = {".py": "python", ".go": "go", ".rs": "rust", ".html": "html", ".htm": "html", ".css": "css"}.get(path.suffix.lower())
            base.language = language
        symbol = base.symbol
        kind = base.kind
        if language == "python" and symbol:
            return self._resolve_python(base, artifact, text)
        if language in {"go", "rust", "html", "css"} and symbol:
            try:
                from bpfw.core.source.tree_sitter_adapter import extract_units
                source_key = (language, base.path)
                if source_key not in self._language_units:
                    units, _has_error = extract_units(language, path, Path(base.path))
                    self._language_units[source_key] = units
                units = self._language_units[source_key]
            except Exception as exc:
                if language == "go":
                    fallback = self._resolve_go_fallback(base, artifact, text)
                    if fallback.resolved:
                        fallback.message = f"Tree-sitter unavailable; used lexical Go fallback: {exc}"
                        return fallback
                return self._stored_fallback(base, artifact, text, f"{language} parser unavailable: {exc}")
            target = symbol
            candidates = [u for u in units if u.symbol == target and (not kind or u.symbol_type == kind)]
            if not candidates:
                # tolerate legacy leaf-only symbols when unambiguous
                leaf = target.split(".")[-1]
                candidates = [u for u in units if u.symbol.split(".")[-1] == leaf and (not kind or u.symbol_type == kind)]
            if len(candidates) == 1:
                unit = candidates[0]
                base.start_line, base.end_line = unit.start_line, unit.end_line
                base.structural_hash = unit.normalized_body_hash
                base.kind = unit.symbol_type
                base.language = unit.language
                base.resolution, base.parser, base.confidence = "EXACT", "tree-sitter", "high"
                base.detected.update({"signature": unit.signature, "unit_id": unit.canonical_id})
                return base
            if len(candidates) > 1:
                base.message = f"Ambiguous symbol: {symbol} ({len(candidates)} matches)"
            if language == "go":
                fallback = self._resolve_go_fallback(base, artifact, text)
                if fallback.resolved:
                    return fallback
            return self._stored_fallback(base, artifact, text, base.message)
        return self._stored_fallback(base, artifact, text, "No semantic code resolver for this artifact")

    def _resolve_go_fallback(self, base: ResolvedArtifact, artifact: dict[str, Any], text: str) -> ResolvedArtifact:
        """Best-effort Go locator used only when Tree-sitter is unavailable.

        The packaged installer installs Tree-sitter by default.  This fallback keeps
        source preview usable in constrained/offline environments without pretending
        to replace the grammar parser used by scanning and verification.
        """
        symbol = base.symbol or ""
        leaf = symbol.split(".")[-1]
        receiver_wanted = symbol.rsplit(".", 1)[0] if "." in symbol else None
        kind = (base.kind or "").lower()
        lines = text.splitlines()
        patterns: list[tuple[re.Pattern[str], str]] = []
        if kind in {"", "function", "method"}:
            patterns.append((re.compile(r"^\s*func\s*(?:\(\s*[^)]*?\*?\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*\("), "callable"))
        if kind in {"", "struct", "interface", "type", "type_alias"}:
            patterns.append((re.compile(r"^\s*type\s+([A-Za-z_][A-Za-z0-9_]*)\s+(struct|interface)\b"), "type"))
            patterns.append((re.compile(r"^\s*type\s+([A-Za-z_][A-Za-z0-9_]*)\s*=?.*$"), "type_simple"))
        if kind in {"constant", "const"}:
            patterns.append((re.compile(r"^\s*const\s+([A-Za-z_][A-Za-z0-9_]*)\b"), "constant"))
        if kind in {"variable", "var"}:
            patterns.append((re.compile(r"^\s*var\s+([A-Za-z_][A-Za-z0-9_]*)\b"), "variable"))

        candidates: list[tuple[int, str]] = []
        for idx, line in enumerate(lines, 1):
            for pattern, ptype in patterns:
                match = pattern.search(line)
                if not match:
                    continue
                if ptype == "callable":
                    receiver, name = match.group(1), match.group(2)
                    if name != leaf: continue
                    if receiver_wanted and receiver != receiver_wanted: continue
                    inferred = "method" if receiver else "function"
                    if kind and kind != inferred: continue
                else:
                    name = match.group(1)
                    if name != leaf: continue
                candidates.append((idx, ptype))
        if len(candidates) != 1:
            return base
        start, ptype = candidates[0]
        end = start
        # Expand braces for functions, structs, interfaces, and grouped declarations.
        balance = 0; opened = False
        in_block_comment = False
        for idx in range(start - 1, len(lines)):
            line = lines[idx]
            scrubbed = ""; i = 0; in_string = None
            while i < len(line):
                ch = line[i]; nxt = line[i:i+2]
                if in_block_comment:
                    if nxt == "*/": in_block_comment = False; i += 2; continue
                    i += 1; continue
                if in_string:
                    if ch == "\\" and in_string == '"': i += 2; continue
                    if ch == in_string: in_string = None
                    i += 1; continue
                if nxt == "//": break
                if nxt == "/*": in_block_comment = True; i += 2; continue
                if ch in {'"', "'", "`"}: in_string = ch; i += 1; continue
                scrubbed += ch; i += 1
            balance += scrubbed.count("{") - scrubbed.count("}")
            opened = opened or "{" in scrubbed
            end = idx + 1
            if opened and balance <= 0: break
            if not opened and idx == start - 1: break
        base.start_line, base.end_line = start, end
        base.resolution, base.parser, base.confidence = "EXACT", "go-lexical-fallback", "medium"
        return base

    def _resolve_python(self, base: ResolvedArtifact, artifact: dict[str, Any], text: str) -> ResolvedArtifact:
        snapshot = self._source_repository.get_snapshot(base.path)
        if snapshot is None:
            return self._stored_fallback(base, artifact, text, "Python source could not be parsed")
        if base.path not in self._python_candidates:
            indexed_nodes = self._source_repository.get_indexed_nodes(base.path)
            by_symbol: dict[str, list[tuple[ast.AST, str]]] = {}
            for qualified_symbol, indexed_node in indexed_nodes.items():
                parent_symbol = qualified_symbol.rpartition(".")[0]
                parent = indexed_nodes.get(parent_symbol)
                node_kind = "class" if isinstance(indexed_node.node, ast.ClassDef) else (
                    "method" if parent is not None and isinstance(parent.node, ast.ClassDef) else "function"
                )
                candidate = (indexed_node.node, node_kind)
                by_symbol.setdefault(qualified_symbol, []).append(candidate)
                if "." in qualified_symbol:
                    by_symbol.setdefault(qualified_symbol.rsplit(".", 1)[-1], []).append(candidate)
            self._python_candidates[base.path] = by_symbol
        target = base.symbol or ""
        kind = (base.kind or "").lower()
        candidates = [node for node, node_kind in self._python_candidates[base.path].get(target, [])
                      if not kind or kind == node_kind or (kind == "function" and node_kind == "method")
                      or (kind == "nested_function" and node_kind == "function")
                      or (kind == "nested_class" and node_kind == "class")]
        stored = artifact.get("start_line")
        if len(candidates) > 1 and isinstance(stored, int):
            candidates.sort(key=lambda node: abs(getattr(node, "lineno", 0) - stored))
            candidates = candidates[:1]
        if len(candidates) == 1:
            node = candidates[0]
            decorators = getattr(node, "decorator_list", [])
            base.start_line = min([getattr(d, "lineno", getattr(node, "lineno", 1)) for d in decorators] + [getattr(node, "lineno", 1)])
            base.end_line = getattr(node, "end_lineno", base.start_line)
            segment = ast.get_source_segment(text, node) or ""
            base.structural_hash = hashlib.sha256(segment.encode("utf-8")).hexdigest()
            base.resolution, base.parser, base.confidence = "EXACT", "python-ast", "high"
            return base
        return self._stored_fallback(base, artifact, text, "Python symbol was not resolved uniquely")

    def _resolve_textual(self, base: ResolvedArtifact, artifact: dict[str, Any], text: str) -> ResolvedArtifact:
        selector = artifact.get("selector") if isinstance(artifact.get("selector"), dict) else {}
        kind = str(selector.get("kind") or "").lower()
        value = selector.get("value")
        lines = text.splitlines()
        if kind == "region" and isinstance(value, str):
            start = end = None
            for idx, line in enumerate(lines, 1):
                m = _REGION_START.search(line)
                if m and m.group(1) == value:
                    start = idx + 1
                    continue
                m = _REGION_END.search(line)
                if m and m.group(1) == value and start is not None:
                    end = idx - 1
                    break
            if start is not None and end is not None and end >= start:
                base.start_line, base.end_line = start, end
                base.resolution, base.parser, base.confidence = "EXACT", "bpfw-region", "high"
        elif kind in {"markdown_heading", "heading", "heading_path"}:
            wanted = value[-1] if isinstance(value, list) and value else value
            if isinstance(wanted, str):
                headings = []
                for idx, line in enumerate(lines, 1):
                    m = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
                    if m:
                        headings.append((idx, len(m.group(1)), m.group(2).strip()))
                matches = [(i, level, title) for i, level, title in headings if title.casefold() == wanted.strip().casefold()]
                if len(matches) == 1:
                    start, level, _ = matches[0]
                    end = len(lines)
                    for i, next_level, _title in headings:
                        if i > start and next_level <= level:
                            end = i - 1
                            break
                    base.start_line, base.end_line = start, max(start, end)
                    base.resolution, base.parser, base.confidence = "EXACT", "markdown-heading", "high"
                elif len(matches) > 1:
                    base.message = f"Ambiguous Markdown heading: {wanted}"
        selector_requested = bool(kind)
        if not base.resolved and not selector_requested:
            self._whole_file(base, text, parser="text")
        elif not base.resolved and selector_requested:
            base.message = base.message or f"Text selector did not resolve: {kind}={value!r}"
            return base
        selected = lines[(base.start_line or 1)-1:(base.end_line or len(lines))]
        variables = sorted({m.group(1) for line in selected for pattern in _VAR_PATTERNS for m in pattern.finditer(line)})
        base.detected["variables"] = variables
        base.detected["headings"] = [line.lstrip("#").strip() for line in selected if re.match(r"^#{1,6}\s+", line)]
        return base

    def _resolve_config(self, base: ResolvedArtifact, artifact: dict[str, Any], text: str, suffix: str) -> ResolvedArtifact:
        selector = artifact.get("selector") if isinstance(artifact.get("selector"), dict) else {}
        kind = str(selector.get("kind") or "").lower()
        value = selector.get("value")
        semantic_path = value if isinstance(value, str) else None
        parsed: Any = None
        try:
            if suffix in {".yaml", ".yml"}: parsed = yaml.safe_load(text)
            elif suffix == ".json": parsed = json.loads(text)
            elif suffix == ".toml": parsed = tomllib.loads(text)
        except Exception as exc:
            base.message = f"Config parse error: {exc}"
        if semantic_path and kind in {"yaml_path", "json_path", "toml_path", "path", "key_path"}:
            current = parsed
            exists = True
            for part in semantic_path.split("."):
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    exists = False
                    break
            if exists:
                lines = text.splitlines()
                leaf = semantic_path.split(".")[-1]
                patterns = [
                    re.compile(rf"^\s*{re.escape(leaf)}\s*[:=]"),
                    re.compile(rf'^\s*["\']{re.escape(leaf)}["\']\s*:'),
                ]
                matches = [idx for idx, line in enumerate(lines, 1) if any(p.search(line) for p in patterns)]
                if len(matches) == 1:
                    base.start_line = base.end_line = matches[0]
                    base.resolution, base.parser, base.confidence = "EXACT", f"{suffix[1:]}-path", "medium"
                    base.detected["semantic_path"] = semantic_path
                    base.detected["value_hash"] = hashlib.sha256(json.dumps(current, sort_keys=True, default=str).encode()).hexdigest()
                    return base
            base.message = f"Configuration selector did not resolve: {semantic_path}"
            return base
        return self._whole_file(base, text, parser=f"{suffix[1:] or 'config'}")

    @staticmethod
    def _whole_file(base: ResolvedArtifact, text: str, parser: str) -> ResolvedArtifact:
        lines = text.splitlines()
        base.start_line, base.end_line = 1, max(1, len(lines))
        base.resolution, base.parser, base.confidence = "WHOLE_FILE", parser, "medium"
        return base

    @staticmethod
    def _stored_fallback(base: ResolvedArtifact, artifact: dict[str, Any], text: str, message: str | None) -> ResolvedArtifact:
        start, end = artifact.get("start_line"), artifact.get("end_line")
        if isinstance(start, int) and isinstance(end, int):
            base.start_line, base.end_line = start, end
            base.resolution, base.parser, base.confidence = "FALLBACK", "stored-span", "low"
            base.message = message
            return base
        base.message = message
        return base
