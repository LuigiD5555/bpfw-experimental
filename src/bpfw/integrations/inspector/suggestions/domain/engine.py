"""AST-based domain suggestions using path and origin analysis."""

from typing import Any

from bpfw.integrations.inspector.suggestions.domain.evidence import collect_domain_evidence
from bpfw.integrations.inspector.suggestions.domain.learning import get_last_domain_for_origin
from bpfw.integrations.inspector.suggestions.domain.models import DomainEvidence

# Technical stopwords that should be filtered regardless of frequency
TECHNICAL_STOPWORDS = frozenset({"src", "tests", "test", "__init__", "py", "init"})

# Package or utility folder tokens that are too generic to be functional domains.
# "core" is intentionally allowed because BPFW treats it as a real domain.
BROAD_FOLDER_TOKENS = frozenset({"app", "api", "config", "data", "db", "lib", "main", "models", "utils"})

GENERIC_SYMBOL_TOKENS = frozenset({"error", "exception", "service", "manager", "handler", "helper"})


def suggest_domains(
    block: dict[str, Any],
    project_blocks: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Suggest domains using fixed evidence slots.

    The slot order is fixed:
    [q] folder_based
    [w] file_based
    [e] module_based
    [r] symbol_based
    [t] previous_domain_for_origin
    [y] custom_domain

    Args:
        block: Block dictionary from scanner.
        project_blocks: Optional list of all blocks for origin history lookup.

    Returns:
        List of domain strings in fixed slot order.
    """

    evidence = collect_domain_evidence(block)

    folder_result = _compose_folder_based_domain(evidence)
    file_result = _compose_file_based_domain(evidence)
    module_result = _compose_module_based_domain(evidence)
    symbol_result = _compose_symbol_based_domain(evidence)
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


def _compose_folder_based_domain(evidence: DomainEvidence) -> str | None:
    """Compose domain from the nearest functional folder (slot q).

    Args:
        evidence: Domain evidence payload.

    Returns:
        Domain token candidate.
    """

    for part in reversed(evidence.path_parts[:-1]):
        for token in part.split("_"):
            if _is_domain_token(token):
                return token
    return None


def _compose_file_based_domain(evidence: DomainEvidence) -> str | None:
    """Compose domain from file stem tokens (slot w).

    Args:
        evidence: Domain evidence payload.

    Returns:
        Domain token candidate.
    """

    if not evidence.file_stem:
        return None

    file_tokens = [token for token in evidence.file_stem.split("_") if _is_domain_token(token)]
    for token in file_tokens:
        return token
    return None


def _compose_module_based_domain(evidence: DomainEvidence) -> str | None:
    """Compose domain from the functional parent module (slot e).

    Args:
        evidence: Domain evidence payload.

    Returns:
        Domain token candidate.
    """

    module_tokens = [part for part in evidence.module_parts if _is_domain_token(part)]
    if not module_tokens:
        return None
    if len(module_tokens) >= 2:
        return module_tokens[-2]
    return module_tokens[-1]


def _compose_symbol_based_domain(evidence: DomainEvidence) -> str | None:
    """Compose domain from symbol name tokens (slot r).

    Args:
        evidence: Domain evidence payload.

    Returns:
        Domain token candidate.
    """

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
    evidence: DomainEvidence,
    project_blocks: list[dict[str, Any]],
) -> str | None:
    """Return the last accepted domain used by another block from the same origin.

    Args:
        block: Current block.
        evidence: Current block domain evidence.
        project_blocks: Project blocks for in-memory history lookup.

    Returns:
        Last matching domain or ``None``.
    """

    if not evidence.origin_key:
        return None

    current_identity = _resolve_block_identity(block)
    last_domain = None
    for candidate_block in project_blocks:
        if not isinstance(candidate_block, dict):
            continue
        if _resolve_block_identity(candidate_block) == current_identity:
            continue
        candidate_evidence = collect_domain_evidence(candidate_block)
        if candidate_evidence.origin_key != evidence.origin_key:
            continue
        candidate_domain = _get_domain_value(candidate_block)
        if _is_valid_suggestion_value(candidate_domain):
            last_domain = candidate_domain.strip()
    return last_domain


def _resolve_block_identity(block: dict[str, Any]) -> tuple[str, str, str]:
    """Return a stable identity for excluding the current block from history.

    Args:
        block: Block dictionary.

    Returns:
        Tuple ``(id, path, symbol)``.
    """

    code = block.get("code", {})
    block_id = block.get("id")
    path = code.get("path") if isinstance(code, dict) else ""
    symbol = code.get("symbol") if isinstance(code, dict) else ""
    return (
        str(block_id or "").strip(),
        str(path or "").replace("\\", "/").strip(),
        str(symbol or "").strip(),
    )


def resolve_domain_origin_key(block: dict[str, Any]) -> str:
    """Resolve the code origin key used by domain history.

    Args:
        block: Block dictionary.

    Returns:
        Origin key string.
    """

    evidence = collect_domain_evidence(block)
    return evidence.origin_key


def _is_domain_token(token: str) -> bool:
    """Return whether a token is acceptable as a domain candidate.

    Args:
        token: Raw token text.

    Returns:
        True when token can be used as a domain candidate.
    """

    normalized = token.strip().lower()
    if len(normalized) < 3:
        return False
    if not normalized.isidentifier():
        return False
    if normalized in TECHNICAL_STOPWORDS:
        return False
    if normalized in BROAD_FOLDER_TOKENS:
        return False
    return True


def _is_valid_suggestion_value(value: Any) -> bool:
    """Return whether a suggestion value should be accepted as a domain.

    Args:
        value: Candidate value.

    Returns:
        True when value is a non-placeholder domain string.
    """

    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    if not normalized:
        return False
    if normalized in {"-", "custom"}:
        return False
    return True


def _get_domain_value(block: dict[str, Any]) -> str | None:
    """Extract domain value from one block.

    Args:
        block: Block dictionary.

    Returns:
        Domain string or ``None``.
    """

    value = block.get("domain")
    if isinstance(value, str) and value.strip():
        return value
    return None


def _normalize_domain_suggestion_output(value: str | None) -> str:
    """Normalize domain suggestions to display-safe output.

    Args:
        value: Raw suggestion value.

    Returns:
        Normalized suggestion or ``-`` placeholder.
    """

    if not value:
        return "-"
    normalized = value.strip().lower().replace("-", "_")
    if not normalized:
        return "-"
    return normalized
