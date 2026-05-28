"""PURPOSE domain-specific evidence extraction
DOMAIN  domain suggestions
"""

from typing import Any

from bpfw.integrations.inspector.suggestions.domain.models import DomainEvidence
from bpfw.integrations.inspector.suggestions.domain.tokenizer import tokenize_identifier


def collect_domain_evidence(block: dict[str, Any]) -> DomainEvidence:
    """PURPOSE collect stable domain evidence for one block
    DOMAIN  domain suggestions
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
    """PURPOSE find the code origin key used by domain history
    DOMAIN  domain suggestions
    """

    normalized_module = ".".join(part for part in module.split(".") if part).strip()
    if normalized_module:
        return normalized_module

    path_parts = tuple(part for part in path.replace("\\", "/").split("/") if part)
    if len(path_parts) > 1:
        return "/".join(path_parts[:-1])
    return ""


def _tokenize_text(text: str) -> tuple[str, ...]:
    """PURPOSE split free text into lowercase alphanumeric terms into words
    DOMAIN  domain suggestions
    """

    import re

    return tuple(token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9_]*", text))
