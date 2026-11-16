"""Tree-Sitter-backed extraction for Go, Rust, HTML, and CSS.

The adapters never infer ownership from indentation. Ownership comes from each grammar's
concrete syntax tree and is emitted as an explicit parent_unit_id.
"""

from __future__ import annotations

import hashlib
import importlib
import re
from pathlib import Path
from typing import Any, Callable, Iterable

from bpfw.core.catalog.models import DiscoveredCodeUnit


class LanguageAdapterUnavailable(RuntimeError):
    """Raised when optional parser binaries for one language are not installed."""


_GRAMMAR_MODULES = {
    "go": "tree_sitter_go",
    "rust": "tree_sitter_rust",
    "html": "tree_sitter_html",
    "css": "tree_sitter_css",
}


def parser_for(language: str) -> Any:
    """Create a parser without importing optional native dependencies at BPFW startup."""

    try:
        tree_sitter = importlib.import_module("tree_sitter")
        grammar = importlib.import_module(_GRAMMAR_MODULES[language])
    except (ImportError, KeyError) as error:
        raise LanguageAdapterUnavailable(
            f"Parser for {language} is unavailable; install blueprint-framework[multilang]."
        ) from error
    return tree_sitter.Parser(tree_sitter.Language(grammar.language()))


def extract_units(language: str, path: Path, relative_path: Path) -> tuple[list[DiscoveredCodeUnit], bool]:
    """Parse one file and return units plus the root syntax-error flag."""

    source = path.read_bytes()
    parse_source = _mask_html_template_tokens(source) if language == "html" else source
    tree = parser_for(language).parse(parse_source)
    extractors: dict[str, Callable[[Any, bytes, Path], list[DiscoveredCodeUnit]]] = {
        "go": _extract_go,
        "rust": _extract_rust,
        "html": _extract_html,
        "css": _extract_css,
    }
    return extractors[language](tree.root_node, source, relative_path), bool(tree.root_node.has_error)



_HTML_TEMPLATE_TOKEN_RE = re.compile(
    rb"{%\s*comment\b.*?%}.*?{%\s*endcomment\s*%}|{%.*?%}|{{.*?}}|{#.*?#}",
    re.DOTALL,
)


def _mask_html_template_tokens(source: bytes) -> bytes:
    """Hide Django template syntax from HTML parsing while preserving byte offsets."""

    def mask_token(match: re.Match[bytes]) -> bytes:
        token = match.group()
        placeholder = b"_" if token.startswith(b"{{") else b" "
        return re.sub(rb"[^\r\n]", placeholder, token)

    return _HTML_TEMPLATE_TOKEN_RE.sub(mask_token, source)


def _text(node: Any, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _field_text(node: Any, field: str, source: bytes) -> str:
    child = node.child_by_field_name(field)
    return _text(child, source).strip() if child is not None else ""


def _signature_before_body(node: Any, source: bytes) -> str:
    body = node.child_by_field_name("body")
    end_byte = body.start_byte if body is not None else node.end_byte
    return source[node.start_byte:end_byte].decode("utf-8", errors="replace").rstrip("; \t\r\n")


def _module(relative_path: Path) -> str:
    return ".".join((*relative_path.parent.parts, relative_path.stem))


def _unit_id(language: str, relative_path: Path, symbol: str) -> str:
    return f"{language}:{relative_path.as_posix()}::{symbol}"


def _structural_hash(node: Any, source: bytes) -> str:
    """Hash named leaf tokens inside one dialect; never compare it across languages."""

    tokens: list[str] = []
    stack = [node]
    while stack:
        current = stack.pop()
        named = list(current.named_children)
        if named:
            stack.extend(reversed(named))
        elif current.type not in {"comment"}:
            tokens.append(f"{current.type}:{_text(current, source).strip()}")
    return hashlib.sha256("\x1f".join(tokens).encode("utf-8")).hexdigest()


def _make_unit(
    *,
    language: str,
    relative_path: Path,
    symbol: str,
    kind: str,
    node: Any,
    source: bytes,
    parent_unit_id: str | None = None,
    visibility: str | None = None,
    signature: str | None = None,
    imports: Iterable[str] = (),
    interface_inputs: list[dict[str, Any]] | None = None,
    interface_output: dict[str, Any] | None = None,
) -> DiscoveredCodeUnit:
    module = _module(relative_path)
    return DiscoveredCodeUnit(
        path=relative_path.as_posix(),
        module=module,
        symbol=symbol,
        symbol_type=kind,
        qualified_name=f"{module}.{symbol}",
        start_line=node.start_point.row + 1,
        end_line=node.end_point.row + 1,
        imports=list(imports),
        signature=signature,
        interface_inputs=interface_inputs or [],
        interface_output=interface_output,
        normalized_body_hash=_structural_hash(node, source),
        language=language,
        unit_id=_unit_id(language, relative_path, symbol),
        parent_unit_id=parent_unit_id,
        visibility=visibility,
    )


def _walk(node: Any) -> Iterable[Any]:
    yield node
    for child in node.named_children:
        yield from _walk(child)


def _go_imports(root: Any, source: bytes) -> list[str]:
    imports: list[str] = []
    for node in _walk(root):
        if node.type == "interpreted_string_literal":
            ancestor = node.parent
            if ancestor is not None and ancestor.type == "import_spec":
                imports.append(_text(node, source).strip('"`'))
    return sorted(set(imports))


def _go_receiver(node: Any, source: bytes) -> str:
    receiver = node.child_by_field_name("receiver")
    if receiver is None:
        return ""
    identifiers = [
        _text(candidate, source)
        for candidate in _walk(receiver)
        if candidate.type == "type_identifier"
    ]
    return identifiers[-1] if identifiers else ""


def _go_visibility(name: str) -> str:
    return "public" if name[:1].isupper() else "private"


def _go_interface(node: Any, source: bytes) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    parameters = node.child_by_field_name("parameters")
    inputs: list[dict[str, Any]] = []
    if parameters is not None:
        for parameter in (child for child in parameters.named_children if child.type == "parameter_declaration"):
            type_text = _field_text(parameter, "type", source)
            names = [_text(child, source) for child in parameter.named_children if child.type == "identifier"]
            if not names:
                names = [""]
            inputs.extend({"name": name, "type": type_text or None} for name in names)
    result = node.child_by_field_name("result")
    output = {"type": _text(result, source).strip()} if result is not None else None
    return inputs, output


def _extract_go(root: Any, source: bytes, relative_path: Path) -> list[DiscoveredCodeUnit]:
    imports = _go_imports(root, source)
    units: list[DiscoveredCodeUnit] = []
    for node in root.named_children:
        if node.type == "type_declaration":
            for spec in (child for child in node.named_children if child.type in {"type_spec", "type_alias"}):
                name = _field_text(spec, "name", source)
                type_node = spec.child_by_field_name("type")
                if spec.type == "type_alias":
                    kind = "type_alias"
                elif type_node is not None and type_node.type == "interface_type":
                    kind = "interface"
                elif type_node is not None and type_node.type == "struct_type":
                    kind = "struct"
                else:
                    kind = "type"
                if name:
                    parent = _make_unit(
                        language="go", relative_path=relative_path, symbol=name, kind=kind,
                        node=spec, source=source, visibility=_go_visibility(name), imports=imports,
                        signature=_text(spec, source).split("{", 1)[0].strip(),
                    )
                    units.append(parent)
                    if kind == "interface" and type_node is not None:
                        for member in (item for item in type_node.named_children if item.type == "method_elem"):
                            method_name = _field_text(member, "name", source)
                            if method_name:
                                interface_inputs, interface_output = _go_interface(member, source)
                                units.append(_make_unit(
                                    language="go", relative_path=relative_path,
                                    symbol=f"{name}.{method_name}", kind="method", node=member,
                                    source=source, parent_unit_id=parent.unit_id,
                                    visibility=_go_visibility(method_name), signature=_text(member, source).strip(),
                                    imports=imports,
                                    interface_inputs=interface_inputs, interface_output=interface_output,
                                ))
        elif node.type in {"const_declaration", "var_declaration"}:
            declaration_kind = "constant" if node.type == "const_declaration" else "variable"
            # Go grammar represents grouped declarations as const_spec/var_spec children.
            specs = [child for child in _walk(node) if child.type in {"const_spec", "var_spec"}]
            if not specs:
                specs = [node]
            for spec in specs:
                names = [
                    _text(child, source).strip()
                    for child in spec.named_children
                    if child.type == "identifier"
                ]
                if not names:
                    name = _field_text(spec, "name", source)
                    names = [name] if name else []
                for name in names:
                    if name:
                        units.append(_make_unit(
                            language="go", relative_path=relative_path, symbol=name, kind=declaration_kind,
                            node=spec, source=source, visibility=_go_visibility(name), imports=imports,
                            signature=_text(spec, source).strip(),
                        ))
        elif node.type == "function_declaration":
            name = _field_text(node, "name", source)
            signature = _signature_before_body(node, source)
            interface_inputs, interface_output = _go_interface(node, source)
            units.append(_make_unit(
                language="go", relative_path=relative_path, symbol=name, kind="function", node=node,
                source=source, visibility=_go_visibility(name), signature=signature, imports=imports,
                interface_inputs=interface_inputs, interface_output=interface_output,
            ))
        elif node.type == "method_declaration":
            name = _field_text(node, "name", source)
            receiver = _go_receiver(node, source)
            symbol = f"{receiver}.{name}" if receiver else name
            signature = _signature_before_body(node, source)
            interface_inputs, interface_output = _go_interface(node, source)
            units.append(_make_unit(
                language="go", relative_path=relative_path, symbol=symbol, kind="method", node=node,
                source=source, parent_unit_id=_unit_id("go", relative_path, receiver) if receiver else None,
                visibility=_go_visibility(name), signature=signature, imports=imports,
                interface_inputs=interface_inputs, interface_output=interface_output,
            ))
    return units


_RUST_CONTAINER_KINDS = {
    "struct_item": "struct",
    "enum_item": "enum",
    "trait_item": "trait",
    "impl_item": "impl",
    "mod_item": "module",
}


def _rust_visibility_text(node: Any, source: bytes) -> str:
    visibility = next((child for child in node.named_children if child.type == "visibility_modifier"), None)
    return _text(visibility, source).strip() if visibility is not None else "private"


def _rust_interface(node: Any, source: bytes) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    parameters = node.child_by_field_name("parameters")
    inputs: list[dict[str, Any]] = []
    if parameters is not None:
        for parameter in parameters.named_children:
            if parameter.type == "self_parameter":
                inputs.append({"name": "self", "type": _text(parameter, source).strip()})
            elif parameter.type == "parameter":
                inputs.append({
                    "name": _field_text(parameter, "pattern", source),
                    "type": _field_text(parameter, "type", source) or None,
                })
    result = node.child_by_field_name("return_type")
    output = {"type": _text(result, source).strip()} if result is not None else None
    return inputs, output


def _rust_name(node: Any, source: bytes) -> str:
    if node.type == "impl_item":
        trait = _field_text(node, "trait", source)
        target = _field_text(node, "type", source)
        return f"impl {trait} for {target}" if trait else f"impl {target}"
    return _field_text(node, "name", source)


def _rust_imports(root: Any, source: bytes) -> list[str]:
    return sorted({_text(node, source).removeprefix("use ").rstrip(";").strip()
                   for node in root.named_children if node.type == "use_declaration"})


def _extract_rust(root: Any, source: bytes, relative_path: Path) -> list[DiscoveredCodeUnit]:
    imports = _rust_imports(root, source)
    units: list[DiscoveredCodeUnit] = []

    counters: dict[tuple[str | None, str], int] = {}

    def visit(
        node: Any,
        parent_symbol: str | None = None,
        parent_id: str | None = None,
        parent_kind: str | None = None,
    ) -> None:
        current_symbol = parent_symbol
        current_parent_id = parent_id
        current_kind = parent_kind
        if node.type in _RUST_CONTAINER_KINDS:
            name = _rust_name(node, source)
            if name:
                if node.type == "impl_item":
                    counter_key = (parent_symbol, name)
                    counters[counter_key] = counters.get(counter_key, 0) + 1
                    name = f"{name}[{counters[counter_key]}]"
                symbol = f"{parent_symbol}.{name}" if parent_symbol else name
                kind = _RUST_CONTAINER_KINDS[node.type]
                semantic_parent_id = parent_id
                if node.type == "impl_item":
                    target = _field_text(node, "type", source)
                    target_symbol = f"{parent_symbol}.{target}" if parent_symbol else target
                    semantic_parent_id = _unit_id("rust", relative_path, target_symbol)
                unit = _make_unit(
                    language="rust", relative_path=relative_path, symbol=symbol, kind=kind,
                    node=node, source=source, parent_unit_id=semantic_parent_id,
                    visibility=_rust_visibility_text(node, source), imports=imports,
                    signature=_text(node, source).split("{", 1)[0].strip(),
                )
                units.append(unit)
                current_symbol, current_parent_id = symbol, unit.unit_id
                current_kind = kind
        elif node.type in {"function_item", "function_signature_item"}:
            name = _rust_name(node, source)
            symbol = f"{parent_symbol}.{name}" if parent_symbol else name
            signature = _signature_before_body(node, source)
            interface_inputs, interface_output = _rust_interface(node, source)
            units.append(_make_unit(
                language="rust", relative_path=relative_path, symbol=symbol,
                kind="method" if parent_kind in {"impl", "trait"} else "function",
                node=node, source=source, parent_unit_id=parent_id,
                visibility=_rust_visibility_text(node, source), signature=signature, imports=imports,
                interface_inputs=interface_inputs, interface_output=interface_output,
            ))
            return
        for child in node.named_children:
            visit(child, current_symbol, current_parent_id, current_kind)

    for child in root.named_children:
        visit(child)
    return units


_TAG_RE = re.compile(r"^<\s*([A-Za-z][\w:-]*)")
_ID_RE = re.compile(r"\bid\s*=\s*([\"'])(.*?)\1", re.IGNORECASE | re.DOTALL)


def _html_tag(node: Any, source: bytes) -> tuple[str, str | None]:
    start = next((child for child in node.named_children if child.type in {"start_tag", "self_closing_tag"}), None)
    raw = _text(start or node, source)
    tag_match = _TAG_RE.search(raw)
    id_match = _ID_RE.search(raw)
    return (tag_match.group(1).lower() if tag_match else "element", id_match.group(2) if id_match else None)


def _extract_html(root: Any, source: bytes, relative_path: Path) -> list[DiscoveredCodeUnit]:
    units: list[DiscoveredCodeUnit] = []

    def visit(node: Any, parent_symbol: str | None, parent_id: str | None) -> None:
        if node.type not in {"element", "script_element", "style_element"}:
            for child in node.named_children:
                visit(child, parent_symbol, parent_id)
            return
        tag, html_id = _html_tag(node, source)
        siblings = [child for child in node.parent.named_children if child.type == node.type] if node.parent else [node]
        same_tag = [candidate for candidate in siblings if _html_tag(candidate, source)[0] == tag]
        ordinal = same_tag.index(node) + 1 if node in same_tag else 1
        segment = f"{tag}#{html_id}" if html_id else f"{tag}[{ordinal}]"
        if html_id:
            same_identifier = [candidate for candidate in same_tag if _html_tag(candidate, source)[1] == html_id]
            if len(same_identifier) > 1:
                segment += f"[{same_identifier.index(node) + 1}]"
        symbol = f"{parent_symbol}/{segment}" if parent_symbol else segment
        unit = _make_unit(
            language="html", relative_path=relative_path, symbol=symbol, kind="html_element",
            node=node, source=source, parent_unit_id=parent_id, visibility="document",
            signature=_text(next(iter(node.named_children), node), source).strip(),
        )
        units.append(unit)
        for child in node.named_children:
            visit(child, symbol, unit.unit_id)

    visit(root, None, None)
    return units


def _css_label(node: Any, source: bytes) -> tuple[str, str]:
    if node.type == "rule_set":
        selectors = next((child for child in node.named_children if child.type == "selectors"), None)
        return "css_rule", _text(selectors, source).strip() if selectors else "rule"
    if node.type == "keyframes_statement":
        name = next((child for child in node.named_children if child.type == "keyframes_name"), None)
        return "css_at_rule", f"@keyframes {_text(name, source).strip() if name else 'anonymous'}"
    if node.type == "keyframe_block":
        marker = next(iter(node.named_children), None)
        return "css_keyframe", _text(marker, source).strip() if marker else "keyframe"
    header = _text(node, source).split("{", 1)[0].strip()
    return "css_at_rule", header or node.type


def _extract_css(root: Any, source: bytes, relative_path: Path) -> list[DiscoveredCodeUnit]:
    unit_types = {
        "rule_set", "at_rule", "media_statement", "supports_statement",
        "keyframes_statement", "keyframe_block",
    }
    units: list[DiscoveredCodeUnit] = []
    counters: dict[tuple[str | None, str], int] = {}

    def visit(node: Any, parent_symbol: str | None, parent_id: str | None) -> None:
        current_symbol, current_parent = parent_symbol, parent_id
        if node.type in unit_types:
            kind, label = _css_label(node, source)
            counter_key = (parent_symbol, label)
            counters[counter_key] = counters.get(counter_key, 0) + 1
            segment = f"{label}[{counters[counter_key]}]"
            symbol = f"{parent_symbol} / {segment}" if parent_symbol else segment
            unit = _make_unit(
                language="css", relative_path=relative_path, symbol=symbol, kind=kind,
                node=node, source=source, parent_unit_id=parent_id, visibility="stylesheet",
                signature=label,
            )
            units.append(unit)
            current_symbol, current_parent = symbol, unit.unit_id
        for child in node.named_children:
            visit(child, current_symbol, current_parent)

    visit(root, None, None)
    return units
