"""AST-based domain suggestions using path and vocabulary analysis."""

from dataclasses import dataclass
from typing import Any

from bpfw.catalog.keywords import build_project_vocabulary
from bpfw.catalog.keywords.models import ProjectVocabulary
from bpfw.catalog.keywords.tokenizer import tokenize_identifier
from bpfw.catalog.learning import get_last_domain_for_origin
from bpfw.catalog.schema import get_code


# Technical stopwords that should be filtered regardless of frequency
TECHNICAL_STOPWORDS = frozenset(
    {"src", "tests", "test", "__init__", "py", "init"}
)

# Package or utility folder tokens that are too generic to be functional domains.
# "core" is intentionally allowed because BPFW treats it as a real domain.
BROAD_FOLDER_TOKENS = frozenset(
    {"app", "api", "config", "data", "db", "lib", "main", "models", "utils"}
)

GENERIC_SYMBOL_TOKENS = frozenset(
    {"error", "exception", "service", "manager", "handler", "helper"}
)


@dataclass(frozen=True, slots=True)
class DomainSuggestion:
    """Represent one deterministic domain suggestion."""

    text: str
    evidence: tuple[str, ...]


def suggest_domains(
    block: dict[str, Any],
    project_blocks: list[dict[str, Any]] | None = None,
) -> list[str]:
    """
    Suggest domains using fixed evidence slots.

    The slot order is fixed:
    [q] folder_based
    [w] file_based
    [e] module_based
    [r] symbol_based
    [t] previous_domain_for_origin
    [y] custom_domain

    No dynamic sorting or reordering is performed.

    Args:
        block: Block dictionary from scanner.
        project_blocks: Optional list of all blocks for vocabulary and origin history.

    Returns:
        List of domain strings in fixed slot order.
    """

    vocabulary = None
    if project_blocks:
        vocabulary = build_project_vocabulary(project_blocks)

    evidence = _collect_domain_evidence(block)

    folder_result = _compose_folder_based_domain(evidence, vocabulary)
    file_result = _compose_file_based_domain(evidence, vocabulary)
    module_result = _compose_module_based_domain(evidence, vocabulary)
    symbol_result = _compose_symbol_based_domain(evidence, vocabulary)
    previous_origin_result = _compose_previous_origin_domain(
        block=block,
        evidence=evidence,
        project_blocks=project_blocks or [],
    )
    if not previous_origin_result:
        previous_origin_result = get_last_domain_for_origin(evidence.origin_key)

    return [
        _normalize_domain_suggestion_output(folder_result),
        _normalize_domain_suggestion_output(file_result),
        _normalize_domain_suggestion_output(module_result),
        _normalize_domain_suggestion_output(symbol_result),
        _normalize_domain_suggestion_output(previous_origin_result),
        "custom",
    ]


@dataclass(frozen=True, slots=True)
class _DomainEvidence:
    """Raw domain evidence collected from one block."""

    path_parts: tuple[str, ...]
    module_parts: tuple[str, ...]
    symbol_tokens: tuple[str, ...]
    file_stem: str
    docstring_tokens: tuple[str, ...]
    origin_key: str


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

    normalized_path = path.replace("\\", "/")
    path_parts = tuple(part for part in normalized_path.split("/") if part)
    module_parts = tuple(part for part in module.split(".") if part)
    file_stem = path_parts[-1].removesuffix(".py") if path_parts else ""
    origin_key = _resolve_origin_key(path=normalized_path, module=module)

    symbol_tokens = tuple(tokenize_identifier(symbol))
    docstring_tokens = tuple(_tokenize_text(docstring))

    return _DomainEvidence(
        path_parts=path_parts,
        module_parts=module_parts,
        symbol_tokens=symbol_tokens,
        file_stem=file_stem,
        docstring_tokens=docstring_tokens,
        origin_key=origin_key,
    )


def _compose_folder_based_domain(
    evidence: _DomainEvidence,
    vocabulary: ProjectVocabulary | None,
) -> str | None:
    """Compose domain from the nearest functional folder (slot q)."""

    for part in reversed(evidence.path_parts[:-1]):
        for token in part.split("_"):
            if _is_domain_token(token):
                return token
    return None


def _compose_file_based_domain(
    evidence: _DomainEvidence,
    vocabulary: ProjectVocabulary | None,
) -> str | None:
    """Compose domain from file stem tokens (slot w)."""

    if not evidence.file_stem:
        return None

    file_tokens = [token for token in evidence.file_stem.split("_") if _is_domain_token(token)]
    for token in file_tokens:
        return token
    return None


def _compose_module_based_domain(
    evidence: _DomainEvidence,
    vocabulary: ProjectVocabulary | None,
) -> str | None:
    """Compose domain from the functional parent module (slot e)."""

    module_tokens = [part for part in evidence.module_parts if _is_domain_token(part)]
    if not module_tokens:
        return None
    if len(module_tokens) >= 2:
        return module_tokens[-2]
    return module_tokens[-1]


def _compose_symbol_based_domain(
    evidence: _DomainEvidence,
    vocabulary: ProjectVocabulary | None,
) -> str | None:
    """Compose domain from symbol name tokens (slot r)."""

    symbol_tokens = []
    for token in evidence.symbol_tokens:
        if not _is_domain_token(token):
            continue
        if token in GENERIC_SYMBOL_TOKENS:
            continue
        symbol_tokens.append(token)
    if symbol_tokens:
        return symbol_tokens[0]
    return None


def _compose_previous_origin_domain(
    block: dict[str, Any],
    evidence: _DomainEvidence,
    project_blocks: list[dict[str, Any]],
) -> str | None:
    """Return the last accepted domain used by another block from the same origin."""

    if not evidence.origin_key:
        return None

    current_identity = _resolve_block_identity(block)
    last_domain = None
    for candidate_block in project_blocks:
        if not isinstance(candidate_block, dict):
            continue
        if _resolve_block_identity(candidate_block) == current_identity:
            continue
        candidate_evidence = _collect_domain_evidence(candidate_block)
        if candidate_evidence.origin_key != evidence.origin_key:
            continue
        candidate_domain = _get_domain_value(candidate_block)
        if _is_valid_suggestion_value(candidate_domain):
            last_domain = candidate_domain.strip()
    return last_domain


def _resolve_block_identity(block: dict[str, Any]) -> tuple[str, str, str]:
    """Return a stable identity for excluding the current block from history."""

    code = get_code(block)
    block_id = block.get("id")
    path = code.get("path") if isinstance(code, dict) else ""
    symbol = code.get("symbol") if isinstance(code, dict) else ""
    return (
        str(block_id or "").strip(),
        str(path or "").replace("\\", "/").strip(),
        str(symbol or "").strip(),
    )


def resolve_domain_origin_key(block: dict[str, Any]) -> str:
    """Resolve the code origin key used by domain history."""

    evidence = _collect_domain_evidence(block)
    return evidence.origin_key


def _resolve_origin_key(path: str, module: str) -> str:
    """Resolve the code origin used by the previous-domain slot."""

    normalized_module = ".".join(part for part in module.split(".") if part).strip()
    if normalized_module:
        return normalized_module

    path_parts = tuple(part for part in path.replace("\\", "/").split("/") if part)
    if len(path_parts) > 1:
        return "/".join(path_parts[:-1])
    return ""


def _get_domain_value(block: dict[str, Any]) -> str:
    """Return the block domain value."""

    value = block.get("domain")
    return value if isinstance(value, str) else ""


def _is_valid_suggestion_value(value: str) -> bool:
    """Return True when a domain suggestion value is selectable."""

    normalized = value.strip()
    return bool(normalized and normalized != "-" and normalized != "custom")


def _normalize_domain_suggestion_output(value: str | None) -> str:
    """Return domain suggestion text in canonical lowercase form."""

    if not isinstance(value, str):
        return "-"
    normalized = " ".join(value.strip().lower().split())
    if not normalized or normalized in {"-", "custom"}:
        return "-"
    return normalized


def _is_domain_token(token: str) -> bool:
    """Return True when token is useful as a fixed-slot domain value."""

    return bool(token and token not in TECHNICAL_STOPWORDS and token not in BROAD_FOLDER_TOKENS)


def _tokenize_text(text: str) -> list[str]:
    """Tokenize free text into words."""

    import re

    tokens = re.findall(r"[A-Za-z][A-Za-z0-9]*", text)
    return [token.lower() for token in tokens if token]
