"""AST-based domain suggestions using path and vocabulary analysis."""

from dataclasses import dataclass
from typing import Any

from bpfw.catalog.keywords import build_project_vocabulary
from bpfw.catalog.keywords.models import ProjectVocabulary
from bpfw.catalog.keywords.tokenizer import tokenize_identifier
from bpfw.catalog.schema import get_code


# Technical stopwords that should be filtered regardless of frequency
TECHNICAL_STOPWORDS = frozenset(
    {"src", "tests", "test", "__init__", "py", "init"}
)

# Broad folder tokens that are too generic to be meaningful domains
BROAD_FOLDER_TOKENS = frozenset(
    {"app", "api", "auth", "config", "core", "data", "db", "lib", "main", "models", "utils"}
)


@dataclass(frozen=True, slots=True)
class DomainSuggestion:
    """Represent one deterministic domain suggestion."""

    text: str
    score: int
    evidence: tuple[str, ...]


def suggest_domains(
    block: dict[str, Any],
    project_blocks: list[dict[str, Any]] | None = None,
) -> list[str]:
    """
    Suggest domains using path analysis and vocabulary.

    This implementation uses fixed slot ordering:
    [q] folder_based
    [w] file_based
    [e] module_based
    [r] symbol_based
    [t] fallback_domain
    [y] custom_domain

    No dynamic sorting, ranking, or reordering is performed.

    Args:
        block: Block dictionary from scanner.
        project_blocks: Optional list of all blocks for vocabulary building.

    Returns:
        List of domain strings in fixed slot order.
    """
    # Build project vocabulary if blocks provided
    vocabulary = None
    if project_blocks:
        vocabulary = build_project_vocabulary(project_blocks)

    # Collect evidence from block
    evidence = _collect_domain_evidence(block)

    # Compose candidates for each fixed slot
    folder_result = _compose_folder_based_domain(evidence, vocabulary)
    file_result = _compose_file_based_domain(evidence, vocabulary)
    module_result = _compose_module_based_domain(evidence, vocabulary)
    symbol_result = _compose_symbol_based_domain(evidence, vocabulary)
    fallback_result = _compose_fallback_domain(evidence)

    # Return domains in fixed slot order
    return [
        folder_result or "-",
        file_result or "-",
        module_result or "-",
        symbol_result or "-",
        fallback_result or "-",
        "custom",  # Custom domain slot
    ]


@dataclass(frozen=True, slots=True)
class _DomainEvidence:
    """Raw domain evidence collected from one block."""

    path_parts: tuple[str, ...]
    module_parts: tuple[str, ...]
    symbol_tokens: tuple[str, ...]
    file_stem: str
    docstring_tokens: tuple[str, ...]


def _collect_domain_evidence(block: dict[str, Any]) -> _DomainEvidence:
    """Collect deterministic evidence used to suggest functional domains."""

    location = get_code(block)
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

    # Normalize path
    normalized_path = path.replace("\\", "/")
    path_parts = tuple(part for part in normalized_path.split("/") if part)
    module_parts = tuple(part for part in module.split(".") if part)
    file_stem = path_parts[-1].removesuffix(".py") if path_parts else ""

    # Tokenize
    symbol_tokens = tuple(tokenize_identifier(symbol))
    docstring_tokens = tuple(_tokenize_text(docstring))

    return _DomainEvidence(
        path_parts=path_parts,
        module_parts=module_parts,
        symbol_tokens=symbol_tokens,
        file_stem=file_stem,
        docstring_tokens=docstring_tokens,
    )


def _compose_folder_based_domain(
    evidence: _DomainEvidence,
    vocabulary: ProjectVocabulary | None,
) -> str | None:
    """Compose domain from folder path tokens (slot q)."""

    # Extract folder tokens (excluding file name)
    folder_tokens = [
        token
        for part in evidence.path_parts[:-1]
        for token in part.split("_")
        if token and token not in TECHNICAL_STOPWORDS and token not in BROAD_FOLDER_TOKENS
    ]

    # Return first valid folder token
    for token in folder_tokens:
        if token and token not in TECHNICAL_STOPWORDS and token not in BROAD_FOLDER_TOKENS:
            return token

    return None


def _compose_file_based_domain(
    evidence: _DomainEvidence,
    vocabulary: ProjectVocabulary | None,
) -> str | None:
    """Compose domain from file stem tokens (slot w)."""

    if not evidence.file_stem:
        return None

    # Extract file stem tokens
    file_tokens = [
        t
        for t in evidence.file_stem.split("_")
        if t and t not in TECHNICAL_STOPWORDS and t not in BROAD_FOLDER_TOKENS
    ]

    # Return first valid file token
    for token in file_tokens:
        return token

    return None


def _compose_module_based_domain(
    evidence: _DomainEvidence,
    vocabulary: ProjectVocabulary | None,
) -> str | None:
    """Compose domain from module path tokens (slot e)."""

    # Extract module tokens
    module_tokens = [
        part
        for part in evidence.module_parts
        if part and part not in TECHNICAL_STOPWORDS and part not in BROAD_FOLDER_TOKENS
    ]

    # Return last valid module token
    if module_tokens:
        return module_tokens[-1]

    return None


def _compose_symbol_based_domain(
    evidence: _DomainEvidence,
    vocabulary: ProjectVocabulary | None,
) -> str | None:
    """Compose domain from symbol name tokens (slot r)."""

    # Extract symbol tokens
    symbol_tokens = []
    for token in evidence.symbol_tokens:
        if token in TECHNICAL_STOPWORDS:
            continue
        if token in BROAD_FOLDER_TOKENS:
            continue
        # Filter out generic tokens if vocabulary available
        if vocabulary and vocabulary.is_common_token(token, threshold=0.7):
            continue
        symbol_tokens.append(token)

    # Return first valid symbol token
    if symbol_tokens:
        return symbol_tokens[0]

    return None


def _compose_fallback_domain(evidence: _DomainEvidence) -> str | None:
    """Compose fallback domain from generic sources (slot t)."""

    fallback_tokens = ("core", "general", "shared", "misc", "system")

    # Try to find a fallback from path or module
    all_path_tokens = list(evidence.path_parts[:-1])
    if evidence.file_stem:
        all_path_tokens.append(evidence.file_stem)

    for token in fallback_tokens:
        if token in all_path_tokens or token in evidence.module_parts:
            return token

    # Return first fallback token as default
    return fallback_tokens[0] if fallback_tokens else None


def _tokenize_text(text: str) -> list[str]:
    """Tokenize free text into words."""

    import re

    tokens = re.findall(r"[A-Za-z][A-Za-z0-9]*", text)
    return [token.lower() for token in tokens if token]