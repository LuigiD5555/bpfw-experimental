"""Hierarchical code preview rendering for the inspector."""

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class _BlockMetadata:
    """Store authority metadata resolved for one code symbol."""

    purpose: str | None
    status: str | None


@dataclass(frozen=True)
class _FoldedChild:
    """Store rendering metadata for one folded child node."""

    start_line: int
    end_line: int
    replacement_line: str


@dataclass(frozen=True)
class _CallReplacement:
    """Store one source-line replacement for a known call."""

    line_number: int
    start_column: int
    end_column: int
    text: str


class _HierarchicalCodePreviewRenderer:
    """Render parent code while folding reviewed children into purpose summaries."""

    def __init__(
        self,
        project_root: Path,
        block: dict[str, Any],
        project_blocks: list[dict[str, Any]] | None = None,
    ) -> None:
        """Initialize the hierarchical preview renderer.

        Args:
            project_root: Project root containing the inspected source file.
            block: Inspector block dictionary being rendered.
            project_blocks: Current authority blocks used to resolve child purposes.
        """
        self.project_root = project_root
        self.block = block
        self.project_blocks = project_blocks or []
        self.location = block.get("code", {}) if isinstance(block.get("code"), dict) else {}
        self.relative_path = _clean_string(self.location.get("path"))
        self.symbol = _clean_string(self.location.get("symbol"))
        self.symbol_type = _clean_string(self.location.get("kind"))
        self.source_text = ""
        self.source_lines: list[str] = []
        self.metadata_by_key = self._build_metadata_index()

    def render(self) -> list[str] | None:
        """Render a folded hierarchical preview when the block has child units.

        Returns:
            Numbered folded preview lines, or ``None`` when the block should use
            the normal source preview.
        """
        if self.relative_path is None or self.symbol is None or self.symbol_type is None:
            return None

        source_path = self.project_root / self.relative_path
        if not source_path.exists():
            return None

        try:
            self.source_text = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        self.source_lines = self.source_text.splitlines()
        try:
            module_ast = ast.parse(self.source_text)
        except SyntaxError:
            return None

        target_node = self._find_target_node(module_ast)
        if target_node is None or not _has_body(target_node):
            return None

        direct_children = self._direct_child_definitions(target_node)
        foldable_children = [child for child in direct_children if not self._should_keep_child_inline(child, target_node)]
        folded_children = self._build_folded_children(foldable_children, target_node)
        call_replacements = self._build_call_replacements(target_node, folded_children)
        if not folded_children and not call_replacements:
            return None
        return self._render_lines(target_node, folded_children, call_replacements)

    def _build_metadata_index(self) -> dict[tuple[str, str, str], _BlockMetadata]:
        """Build a metadata lookup keyed by path, symbol, and kind.

        Returns:
            Mapping from code target keys to resolved authority metadata.
        """
        metadata_by_key: dict[tuple[str, str, str], _BlockMetadata] = {}
        for block in self.project_blocks:
            if not isinstance(block, dict):
                continue
            code = block.get("code")
            if not isinstance(code, dict):
                continue
            path = _clean_string(code.get("path"))
            symbol = _clean_string(code.get("symbol"))
            kind = _clean_string(code.get("kind"))
            if path is None or symbol is None or kind is None:
                continue
            metadata_by_key[(path, symbol, kind)] = _BlockMetadata(
                purpose=_clean_string(block.get("purpose")),
                status=_clean_string(block.get("status")),
            )
        return metadata_by_key

    def _find_target_node(self, module_ast: ast.Module) -> ast.AST | None:
        """Find the AST node for the block being rendered.

        Args:
            module_ast: Parsed Python module.

        Returns:
            Matching class or function node when it can be found.
        """
        target_name = self.symbol.split(".")[-1] if self.symbol is not None else None
        if target_name is None:
            return None
        target_line = self.location.get("start_line")
        target_line_value = target_line if isinstance(target_line, int) else None
        candidate_types = _candidate_types_for_symbol_type(self.symbol_type or "")

        for node in ast.walk(module_ast):
            if not isinstance(node, candidate_types):
                continue
            if getattr(node, "name", None) != target_name:
                continue
            if target_line_value is not None and getattr(node, "lineno", None) != target_line_value:
                continue
            return node

        if target_line_value is None:
            return None
        for node in ast.walk(module_ast):
            if not isinstance(node, candidate_types):
                continue
            if getattr(node, "name", None) == target_name:
                return node
        return None

    def _direct_child_definitions(self, node: ast.AST) -> list[ast.AST]:
        """Return direct class/function children from one AST node.

        Args:
            node: Parent AST node.

        Returns:
            Direct child definitions in source order.
        """
        if not _has_body(node):
            return []
        return [
            statement
            for statement in node.body
            if isinstance(statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ]

    def _should_keep_child_inline(self, child: ast.AST, parent: ast.AST) -> bool:
        """Return whether a child definition should remain expanded in the parent.

        Args:
            child: Direct child definition.
            parent: Parent definition.

        Returns:
            True when the child should not be folded.
        """
        if isinstance(parent, ast.ClassDef) and isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return child.name == "__init__"
        return False

    def _build_folded_children(self, children: list[ast.AST], parent: ast.AST) -> list[_FoldedChild]:
        """Build folded child replacement records.

        Args:
            children: Direct child definitions to fold.
            parent: Parent AST node.

        Returns:
            Folded child replacement records.
        """
        folded_children: list[_FoldedChild] = []
        for child in children:
            start_line = _decorator_aware_start_line(child)
            end_line = getattr(child, "end_lineno", getattr(child, "lineno", start_line))
            indent = self._line_indent(start_line)
            child_symbol = self._child_symbol(child)
            child_kind = self._child_kind(child, parent)
            status = self._display_status(child_symbol, child_kind)
            purpose = self._display_purpose(child, child_symbol, child_kind)
            parameters = self._definition_parameters(child, child_kind)
            folded_children.append(
                _FoldedChild(
                    start_line=start_line,
                    end_line=end_line,
                    replacement_line=f"{indent}{status} {purpose}({parameters})",
                )
            )
        return folded_children

    def _build_call_replacements(
        self,
        target_node: ast.AST,
        folded_children: list[_FoldedChild],
    ) -> list[_CallReplacement]:
        """Build safe replacements for calls to known reviewed children.

        Args:
            target_node: Parent AST node being rendered.
            folded_children: Folded child ranges that should not be rewritten.

        Returns:
            Call replacement records that preserve real call-site arguments.
        """
        replacements: list[_CallReplacement] = []
        folded_ranges = [(child.start_line, child.end_line) for child in folded_children]
        for node in ast.walk(target_node):
            if not isinstance(node, ast.Call):
                continue
            line_number = getattr(node, "lineno", None)
            end_line_number = getattr(node, "end_lineno", None)
            start_column = getattr(node, "col_offset", None)
            end_column = getattr(node, "end_col_offset", None)
            if not isinstance(line_number, int) or not isinstance(end_line_number, int):
                continue
            if line_number != end_line_number:
                continue
            if not isinstance(start_column, int) or not isinstance(end_column, int):
                continue
            if _line_is_inside_ranges(line_number, folded_ranges):
                continue
            resolved = self._resolve_call(node)
            if resolved is None:
                continue
            status = self._display_status(resolved[0], resolved[1])
            purpose = self._purpose_for_key(resolved[0], resolved[1])
            if purpose is None:
                continue
            arguments = self._call_arguments(node)
            replacements.append(
                _CallReplacement(
                    line_number=line_number,
                    start_column=start_column,
                    end_column=end_column,
                    text=f"{status} {purpose}({arguments})",
                )
            )
        return replacements

    def _render_lines(
        self,
        target_node: ast.AST,
        folded_children: list[_FoldedChild],
        call_replacements: list[_CallReplacement],
    ) -> list[str]:
        """Render numbered source lines with folded children and call replacements.

        Args:
            target_node: Parent AST node being rendered.
            folded_children: Child definition fold records.
            call_replacements: Safe call-site replacement records.

        Returns:
            Numbered preview lines.
        """
        start_line = _decorator_aware_start_line(target_node)
        end_line = getattr(target_node, "end_lineno", start_line)
        displayed_start_line = _find_display_start_line(self.source_lines, start_line)
        displayed_end_line = _find_display_end_line(self.source_lines, end_line)
        line_number_width = max(len(str(displayed_end_line)), 3)
        folded_by_start = {child.start_line: child for child in folded_children}
        folded_ranges = [(child.start_line, child.end_line) for child in folded_children]
        replacements_by_line = self._group_replacements_by_line(call_replacements)

        rendered_lines: list[str] = []
        line_number = displayed_start_line
        while line_number <= displayed_end_line:
            folded_child = folded_by_start.get(line_number)
            if folded_child is not None:
                rendered_lines.append(
                    f"{line_number:>{line_number_width}}  {folded_child.replacement_line}"
                )
                line_number = folded_child.end_line + 1
                continue
            if _line_is_inside_ranges(line_number, folded_ranges):
                line_number += 1
                continue
            source_line = self.source_lines[line_number - 1] if line_number - 1 < len(self.source_lines) else ""
            source_line = self._apply_line_replacements(
                source_line=source_line,
                replacements=replacements_by_line.get(line_number, []),
            )
            rendered_lines.append(f"{line_number:>{line_number_width}}  {source_line}")
            line_number += 1
        return rendered_lines

    def _group_replacements_by_line(
        self,
        replacements: list[_CallReplacement],
    ) -> dict[int, list[_CallReplacement]]:
        """Group call replacements by source line.

        Args:
            replacements: Call replacement records.

        Returns:
            Mapping from line number to replacements ordered right-to-left.
        """
        grouped: dict[int, list[_CallReplacement]] = {}
        for replacement in replacements:
            grouped.setdefault(replacement.line_number, []).append(replacement)
        for line_replacements in grouped.values():
            line_replacements.sort(key=lambda item: item.start_column, reverse=True)
        return grouped

    def _apply_line_replacements(
        self,
        source_line: str,
        replacements: list[_CallReplacement],
    ) -> str:
        """Apply non-overlapping call replacements to one source line.

        Args:
            source_line: Original source line.
            replacements: Replacement records for the line.

        Returns:
            Source line with safe replacements applied.
        """
        if not replacements:
            return source_line
        rendered_line = source_line
        occupied_until: int | None = None
        for replacement in replacements:
            if occupied_until is not None and replacement.end_column > occupied_until:
                continue
            rendered_line = (
                rendered_line[:replacement.start_column]
                + replacement.text
                + rendered_line[replacement.end_column:]
            )
            occupied_until = replacement.start_column
        return rendered_line

    def _line_indent(self, line_number: int) -> str:
        """Return leading whitespace for a source line.

        Args:
            line_number: One-based source line number.

        Returns:
            Leading whitespace for the line.
        """
        if line_number < 1 or line_number > len(self.source_lines):
            return ""
        line = self.source_lines[line_number - 1]
        return line[: len(line) - len(line.lstrip())]

    def _child_symbol(self, child: ast.AST) -> str:
        """Return the dotted child symbol for a direct child node.

        Args:
            child: Direct child definition.

        Returns:
            Dotted child symbol.
        """
        child_name = getattr(child, "name", "")
        if self.symbol is None:
            return child_name
        return f"{self.symbol}.{child_name}"

    def _child_kind(self, child: ast.AST, parent: ast.AST) -> str:
        """Return the catalog kind for a direct child node.

        Args:
            child: Direct child definition.
            parent: Parent definition.

        Returns:
            Catalog symbol kind.
        """
        if isinstance(child, ast.ClassDef):
            return "nested_class"
        if isinstance(parent, ast.ClassDef):
            return "method"
        return "nested_function"

    def _display_status(self, symbol: str, kind: str) -> str:
        """Return display status for one child symbol.

        Args:
            symbol: Dotted child symbol.
            kind: Catalog child kind.

        Returns:
            Bracketed status label.
        """
        metadata = self._metadata_for_key(symbol, kind)
        if metadata is not None and metadata.purpose is not None:
            return "[reviewed]"
        if metadata is not None:
            return "[pending]"
        if _is_private_or_dunder_symbol(symbol):
            return "[internal]"
        return "[pending]"

    def _display_purpose(self, child: ast.AST, symbol: str, kind: str) -> str:
        """Return display purpose for one child definition.

        Args:
            child: Direct child definition.
            symbol: Dotted child symbol.
            kind: Catalog child kind.

        Returns:
            Purpose text or deterministic fallback.
        """
        purpose = self._purpose_for_key(symbol, kind)
        if purpose is not None:
            return purpose
        docstring = ast.get_docstring(child)
        if docstring:
            first_line = docstring.strip().splitlines()[0].strip().rstrip(".")
            if first_line:
                return first_line[:1].lower() + first_line[1:]
        return _humanize_identifier(getattr(child, "name", "symbol"))

    def _metadata_for_key(self, symbol: str, kind: str) -> _BlockMetadata | None:
        """Return metadata for a code target.

        Args:
            symbol: Dotted code symbol.
            kind: Catalog symbol kind.

        Returns:
            Matching metadata or None.
        """
        if self.relative_path is None:
            return None
        return self.metadata_by_key.get((self.relative_path, symbol, kind))

    def _purpose_for_key(self, symbol: str, kind: str) -> str | None:
        """Return an authority purpose for a code target.

        Args:
            symbol: Dotted code symbol.
            kind: Catalog symbol kind.

        Returns:
            Purpose when the target is already known.
        """
        metadata = self._metadata_for_key(symbol, kind)
        if metadata is None:
            return None
        return metadata.purpose

    def _definition_parameters(self, node: ast.AST, kind: str) -> str:
        """Return compact parameter names for a definition.

        Args:
            node: Class or function definition node.
            kind: Catalog child kind.

        Returns:
            Comma-separated parameter names without invented placeholders.
        """
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ""
        parameters: list[str] = []
        for arg in [*node.args.posonlyargs, *node.args.args]:
            if kind == "method" and arg.arg in {"self", "cls"}:
                continue
            parameters.append(arg.arg)
        if node.args.vararg is not None:
            parameters.append(f"*{node.args.vararg.arg}")
        for arg in node.args.kwonlyargs:
            parameters.append(arg.arg)
        if node.args.kwarg is not None:
            parameters.append(f"**{node.args.kwarg.arg}")
        return ", ".join(parameters)

    def _call_arguments(self, node: ast.Call) -> str:
        """Return real call-site arguments for a call expression.

        Args:
            node: AST call expression.

        Returns:
            Comma-separated source arguments from the original call site.
        """
        arguments: list[str] = []
        for argument in node.args:
            arguments.append(self._source_segment(argument))
        for keyword in node.keywords:
            value_text = self._source_segment(keyword.value)
            if keyword.arg is None:
                arguments.append(f"**{value_text}")
            else:
                arguments.append(f"{keyword.arg}={value_text}")
        return ", ".join(argument for argument in arguments if argument)

    def _source_segment(self, node: ast.AST) -> str:
        """Return source text for an AST expression.

        Args:
            node: AST expression.

        Returns:
            Source segment or a compact unparsing fallback.
        """
        segment = ast.get_source_segment(self.source_text, node)
        if segment is not None:
            return " ".join(segment.strip().split())
        try:
            return ast.unparse(node)
        except (AttributeError, ValueError, TypeError):
            return "-"

    def _resolve_call(self, node: ast.Call) -> tuple[str, str] | None:
        """Resolve a call expression to a known child or project block.

        Args:
            node: AST call expression.

        Returns:
            Tuple of symbol and kind when safely resolved.
        """
        function = node.func
        if isinstance(function, ast.Name):
            nested_symbol = self._resolve_bare_call(function.id)
            if nested_symbol is not None:
                return nested_symbol
        if isinstance(function, ast.Attribute):
            same_class_symbol = self._resolve_same_class_call(function)
            if same_class_symbol is not None:
                return same_class_symbol
        return None

    def _resolve_bare_call(self, name: str) -> tuple[str, str] | None:
        """Resolve a bare call name in the current lexical context.

        Args:
            name: Bare function name.

        Returns:
            Symbol and kind when safely resolved.
        """
        if self.symbol is not None:
            nested_symbol = f"{self.symbol}.{name}"
            if self._metadata_for_key(nested_symbol, "nested_function") is not None:
                return nested_symbol, "nested_function"
        if self._metadata_for_key(name, "function") is not None:
            return name, "function"
        return None

    def _resolve_same_class_call(self, function: ast.Attribute) -> tuple[str, str] | None:
        """Resolve ``self.method`` or ``cls.method`` calls in the same class.

        Args:
            function: Attribute expression used as call target.

        Returns:
            Symbol and method kind when safely resolved.
        """
        if not isinstance(function.value, ast.Name):
            return None
        if function.value.id not in {"self", "cls"}:
            return None
        class_symbol = self._current_class_symbol()
        if class_symbol is None:
            return None
        method_symbol = f"{class_symbol}.{function.attr}"
        if self._metadata_for_key(method_symbol, "method") is not None:
            return method_symbol, "method"
        return None

    def _current_class_symbol(self) -> str | None:
        """Return the enclosing class symbol for the rendered block.

        Returns:
            Dotted class symbol or None.
        """
        if self.symbol is None or self.symbol_type is None:
            return None
        if self.symbol_type in {"class", "nested_class"}:
            return self.symbol
        if self.symbol_type in {"method", "nested_function"}:
            parts = self.symbol.split(".")
            if len(parts) >= 2:
                return ".".join(parts[:-1])
        return None


def _clean_string(value: Any) -> str | None:
    """Return a stripped string or None for blank values.

    Args:
        value: Value to clean.

    Returns:
        Cleaned string or None.
    """
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _has_body(node: ast.AST) -> bool:
    """Return whether an AST node has a body list.

    Args:
        node: AST node.

    Returns:
        True when the node has a body.
    """
    body = getattr(node, "body", None)
    return isinstance(body, list)


def _candidate_types_for_symbol_type(symbol_type: str) -> tuple[type[ast.AST], ...]:
    """Return AST candidate types for a catalog symbol type.

    Args:
        symbol_type: Catalog symbol kind.

    Returns:
        Tuple of AST classes to inspect.
    """
    function_types: tuple[type[ast.AST], ...] = (ast.FunctionDef, ast.AsyncFunctionDef)
    normalized = symbol_type.lower()
    if normalized in {"class", "nested_class"}:
        return (ast.ClassDef,)
    if normalized in {"function", "method", "nested_function"}:
        return function_types
    return (ast.ClassDef, *function_types)


def _decorator_aware_start_line(node: ast.AST) -> int:
    """Return the first source line for a decorated definition.

    Args:
        node: Definition node.

    Returns:
        One-based source line number.
    """
    decorators = getattr(node, "decorator_list", None)
    if decorators:
        return min(decorator.lineno for decorator in decorators)
    return getattr(node, "lineno", 1)


def _line_is_inside_ranges(line_number: int, ranges: list[tuple[int, int]]) -> bool:
    """Return whether a source line is inside any closed range.

    Args:
        line_number: One-based source line number.
        ranges: Closed source-line ranges.

    Returns:
        True when the line is covered by any range.
    """
    return any(start_line <= line_number <= end_line for start_line, end_line in ranges)


def _is_private_or_dunder_symbol(symbol: str) -> bool:
    """Return whether the tail symbol is private or dunder.

    Args:
        symbol: Dotted code symbol.

    Returns:
        True for private or dunder symbol tails.
    """
    tail = symbol.split(".")[-1]
    return tail.startswith("_")


def _humanize_identifier(identifier: str) -> str:
    """Return a deterministic human-readable fallback from an identifier.

    Args:
        identifier: Python identifier.

    Returns:
        Lowercase phrase generated from the identifier.
    """
    cleaned = identifier.strip("_").replace("_", " ").strip()
    return cleaned or identifier


def _find_display_start_line(source_lines: list[str], start_line: int) -> int:
    """Include contiguous blank lines before the block.

    Args:
        source_lines: Source text split into lines.
        start_line: First block line.

    Returns:
        Display start line.
    """
    displayed_start_line = max(start_line, 1)
    while displayed_start_line > 1:
        previous_line = source_lines[displayed_start_line - 2]
        if previous_line.strip():
            break
        displayed_start_line -= 1
    return displayed_start_line


def _find_display_end_line(source_lines: list[str], end_line: int) -> int:
    """Include contiguous blank lines after the block.

    Args:
        source_lines: Source text split into lines.
        end_line: Last block line.

    Returns:
        Display end line.
    """
    displayed_end_line = min(end_line, len(source_lines))
    while displayed_end_line < len(source_lines):
        next_line = source_lines[displayed_end_line]
        if next_line.strip():
            break
        displayed_end_line += 1
    return displayed_end_line
