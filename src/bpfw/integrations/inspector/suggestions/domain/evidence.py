"""Domain-specific evidence extraction."""

from typing import Any

from bpfw.integrations.inspector.suggestions.domain.models import DomainEvidence
from bpfw.integrations.inspector.suggestions.domain.tokenizer import tokenize_identifier


def collect_domain_evidence(block: dict[str, Any]) -> DomainEvidence:
    """Collect deterministic domain evidence for one block.

    Args:
        block: Block dictionary from scanner or authority data.

    Returns:
        Normalized domain evidence used by the domain suggestion engine.
    """

    location = block.get("code", {})
    path = ""
    module = ""
    symbol = ""
    if isinstance(location, dict):
        path_value = location.get("path")
        module_value = location.get("module")
        symbol_value = location.get("symbol")
        path = path_value.strip() if isinstance(path_value, str) else ""
        module = module_value.strip() if isinstance(module_value, str) else ""
        symbol = symbol_value.strip() if isinstance(symbol_value, str) else ""

    detected = block.get("detected")
    docstring = ""
    if isinstance(detected, dict):
        docstring_value = detected.get("docstring")
        if isinstance(docstring_value, str):
            docstring = docstring_value

    normalized_path = path.replace("\\", "/")
    path_parts = tuple(part for part in normalized_path.split("/") if part)
    module_parts = tuple(part for part in module.split(".") if part)
    file_stem = path_parts[-1].removesuffix(".py") if path_parts else ""
    origin_key = resolve_origin_key(path=normalized_path, module=module)

    symbol_tokens = tuple(tokenize_identifier(symbol))
    docstring_tokens = tuple(_tokenize_text(docstring))

    return DomainEvidence(
        path_parts=path_parts,
        module_parts=module_parts,
        symbol_tokens=symbol_tokens,
        file_stem=file_stem,
        docstring_tokens=docstring_tokens,
        origin_key=origin_key,
    )


def resolve_origin_key(path: str, module: str) -> str:
    """Resolve the code origin key used by domain history.

    Args:
        path: Normalized source path string.
        module: Python module path string.

    Returns:
        Stable origin key for historical domain lookup.
    """

    normalized_module = ".".join(part for part in module.split(".") if part).strip()
    if normalized_module:
        return normalized_module

    path_parts = tuple(part for part in path.replace("\\", "/").split("/") if part)
    if len(path_parts) > 1:
        return "/".join(path_parts[:-1])
    return ""


def _tokenize_text(text: str) -> tuple[str, ...]:
    """Tokenize free text into lowercase alphanumeric terms.

    Args:
        text: Raw free-text value.

    Returns:
        Token tuple with deterministic ordering.
    """

    import re

    return tuple(token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9_]*", text))
