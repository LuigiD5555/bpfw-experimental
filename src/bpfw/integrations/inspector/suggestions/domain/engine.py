"""PURPOSE inspector domain suggestions with behavior and origin evidence
DOMAIN  domain suggestions
"""

from typing import Any

from bpfw.integrations.inspector.suggestions.domain.domain_behavior import suggest_behavior_domains
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
    """PURPOSE suggest domains using fixed evidence slots
    DOMAIN  domain suggestions
    """

    evidence = collect_domain_evidence(block)

    current_identity = _resolve_block_identity(block)
    behavior_slots = suggest_behavior_domains(
        block=block,
        project_blocks=project_blocks or [],
        current_identity=current_identity,
    )
    symbol_result = _compose_symbol_based_domain(evidence)
    previous_origin_result = _compose_previous_origin_domain(
        block=block,
        evidence=evidence,
        project_blocks=project_blocks or [],
    )
    if not previous_origin_result:
        previous_origin_result = get_last_domain_for_origin(evidence.origin_key)

    return [
        _normalize_domain_suggestion_output(behavior_slots[0]),
        _normalize_domain_suggestion_output(behavior_slots[1]),
        _normalize_domain_suggestion_output(behavior_slots[2]),
        _normalize_domain_suggestion_output(symbol_result),
        _normalize_domain_suggestion_output(previous_origin_result),
        "custom",
    ]


def _compose_symbol_based_domain(evidence: DomainEvidence) -> str | None:
    """PURPOSE compose domain from symbol name tokens (slot r)
    DOMAIN  domain suggestions
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
    """PURPOSE get the last accepted domain used by another block from the same origin
    DOMAIN  domain suggestions
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
    """PURPOSE get a stable identity for excluding the block from history
    DOMAIN  domain suggestions
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
    """PURPOSE find the code origin key used by domain history
    DOMAIN  domain suggestions
    """

    evidence = collect_domain_evidence(block)
    return evidence.origin_key


def _is_domain_token(token: str) -> bool:
    """PURPOSE check whether a token is acceptable as a domain candidate
    DOMAIN  domain suggestions
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
    """PURPOSE check whether a suggestion value should be accepted as a domain
    DOMAIN  domain suggestions
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
    """PURPOSE get domain value from one block
    DOMAIN  domain suggestions
    """

    value = block.get("domain")
    if isinstance(value, str) and value.strip():
        return value
    return None


def _normalize_domain_suggestion_output(value: str | None) -> str:
    """PURPOSE clean domain suggestions to display-safe output
    DOMAIN  domain suggestions
    """

    if not value:
        return "-"
    stripped = value.strip()
    if stripped == "-":
        return "-"
    normalized = stripped.lower().replace("-", "_")
    if not normalized:
        return "-"
    return normalized
