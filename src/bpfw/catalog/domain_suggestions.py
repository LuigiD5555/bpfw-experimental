"""Deterministic domain suggestions for catalog responsibilities."""

from dataclasses import dataclass
import re
from typing import Any

from bpfw.catalog.learning import load_learning_scores

PACKAGE_ROOT_STOPWORDS = frozenset(
    {"src", "bpfw", "tests", "test", "__init__", "py", "init"}
)
GENERIC_SYMBOL_STOPWORDS = frozenset(
    {
        "service",
        "manager",
        "handler",
        "helper",
        "utils",
        "utility",
        "processor",
        "controller",
        "builder",
        "factory",
        "repository",
        "adapter",
        "client",
        "base",
        "abstract",
        "mixin",
        "model",
        "schema",
        "data",
        "info",
        "item",
        "object",
        "class",
        "function",
        "method",
        "session",
        "run",
        "text",
    }
)
DOCSTRING_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "from",
        "with",
        "one",
        "deterministic",
        "represent",
        "responsibility",
    }
)
BROAD_FOLDER_TOKENS = frozenset({"integrations"})


@dataclass(frozen=True, slots=True)
class DomainSuggestion:
    """Represent one deterministic domain suggestion."""

    text: str
    score: int
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _DomainEvidence:
    """Raw domain evidence collected from one responsibility."""

    path_parts: tuple[str, ...]
    module_parts: tuple[str, ...]
    symbol_tokens: tuple[str, ...]
    file_stem: str
    docstring_tokens: tuple[str, ...]


def suggest_domains(responsibility: dict[str, Any]) -> list[DomainSuggestion]:
    """Suggest deterministic functional domains from responsibility metadata."""

    evidence = collect_domain_evidence(responsibility)
    return rank_domain_suggestions(compose_domain_candidates(evidence))


def collect_domain_evidence(responsibility: dict[str, Any]) -> _DomainEvidence:
    """Collect deterministic evidence used to suggest functional domains."""

    location = responsibility.get("location")
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

    detected = responsibility.get("detected")
    docstring = ""
    if isinstance(detected, dict):
        docstring_value = detected.get("docstring")
        if isinstance(docstring_value, str):
            docstring = docstring_value

    normalized_path = path.replace("\\", "/")
    path_parts = tuple(part for part in normalized_path.split("/") if part)
    module_parts = tuple(part for part in module.split(".") if part)
    file_stem = path_parts[-1].removesuffix(".py") if path_parts else ""
    symbol_tokens = tuple(_split_identifier_tokens(symbol))
    docstring_tokens = tuple(_split_text_tokens(docstring))

    return _DomainEvidence(
        path_parts=path_parts,
        module_parts=module_parts,
        symbol_tokens=symbol_tokens,
        file_stem=file_stem,
        docstring_tokens=docstring_tokens,
    )


def compose_domain_candidates(evidence: _DomainEvidence) -> list[DomainSuggestion]:
    """Compose domain candidates from normalized responsibility evidence."""

    candidates: list[DomainSuggestion] = []

    folder_candidates = [
        _normalize_domain(part)
        for part in evidence.path_parts[:-1]
        if _normalize_domain(part) is not None
    ]
    file_stem = _normalize_domain(evidence.file_stem)
    module_candidates = [
        _normalize_domain(part)
        for part in evidence.module_parts
        if _normalize_domain(part) is not None
    ]
    symbol_candidates = [
        token
        for token in evidence.symbol_tokens
        if token not in PACKAGE_ROOT_STOPWORDS and token not in GENERIC_SYMBOL_STOPWORDS
    ]
    docstring_candidates = [
        token
        for token in evidence.docstring_tokens
        if token not in PACKAGE_ROOT_STOPWORDS
        and token not in GENERIC_SYMBOL_STOPWORDS
        and token not in DOCSTRING_STOPWORDS
    ]

    symbol_set = set(symbol_candidates)
    docstring_set = set(docstring_candidates)
    path_set = set(folder_candidates + ([file_stem] if file_stem else []))
    module_set = set(module_candidates)
    expanded_path_module_tokens: set[str] = set()
    for value in path_set | module_set:
        expanded_path_module_tokens.update(token for token in value.split("_") if token)

    for candidate in folder_candidates:
        score = 40
        evidence_lines = [f"path segment: {candidate}"]
        if candidate in BROAD_FOLDER_TOKENS:
            score -= 15
            evidence_lines.append(f"broad folder: {candidate}")
        if candidate in symbol_set:
            score += 25
            evidence_lines.append(f"symbol token: {candidate}")
        if candidate in module_set:
            score += 20
            evidence_lines.append(f"module segment: {candidate}")
        _append_candidate(candidates, candidate, score, tuple(evidence_lines))

    if file_stem:
        score = 35
        evidence_lines = [f"file stem: {file_stem}"]
        file_tokens = set(file_stem.split("_"))
        if file_tokens & symbol_set:
            score += 15
            evidence_lines.append("symbol overlap")
        _append_candidate(candidates, file_stem, score, tuple(evidence_lines))

    for candidate in module_candidates:
        score = 30
        evidence_lines = [f"module segment: {candidate}"]
        if candidate in symbol_set:
            score += 20
            evidence_lines.append(f"symbol token: {candidate}")
        if candidate in path_set:
            score += 15
            evidence_lines.append(f"path segment: {candidate}")
        _append_candidate(candidates, candidate, score, tuple(evidence_lines))

    for candidate in symbol_candidates:
        score = 25
        evidence_lines = [f"symbol token: {candidate}"]
        if candidate in docstring_set:
            score += 15
            evidence_lines.append(f"docstring token: {candidate}")
        if (
            candidate in path_set
            or candidate in module_set
            or candidate in expanded_path_module_tokens
        ):
            score += 25
            evidence_lines.append(f"path/module token: {candidate}")
        _append_candidate(candidates, candidate, score, tuple(evidence_lines))

    return candidates


def rank_domain_suggestions(candidates: list[DomainSuggestion]) -> list[DomainSuggestion]:
    """Rank, deduplicate, and limit deterministic domain suggestions."""

    learning_scores = load_learning_scores().domain_boost
    by_text: dict[str, DomainSuggestion] = {}
    for candidate in candidates:
        normalized = candidate.text.strip().lower()
        if not normalized:
            continue
        learned_boost = min(12, learning_scores.get(normalized, 0) * 2)
        boosted_score = candidate.score + learned_boost
        existing = by_text.get(normalized)
        if existing is None or boosted_score > existing.score:
            by_text[normalized] = DomainSuggestion(
                text=normalized,
                score=boosted_score,
                evidence=candidate.evidence + ((f"learned_boost:{learned_boost}",) if learned_boost else ()),
            )

    ranked = sorted(
        by_text.values(),
        key=lambda suggestion: (-suggestion.score, len(suggestion.text), suggestion.text),
    )
    return ranked[:3]


def _append_candidate(
    candidates: list[DomainSuggestion],
    text: str | None,
    score: int,
    evidence: tuple[str, ...],
) -> None:
    """Append one candidate if the value is valid."""

    if text is None:
        return
    cleaned = text.strip().lower().replace("-", "_")
    if not cleaned:
        return
    if cleaned in PACKAGE_ROOT_STOPWORDS:
        return
    if cleaned.endswith(".py"):
        cleaned = cleaned[:-3]
    if not cleaned or cleaned in PACKAGE_ROOT_STOPWORDS:
        return
    candidates.append(DomainSuggestion(text=cleaned, score=score, evidence=evidence))


def _normalize_domain(value: str) -> str | None:
    """Normalize one possible domain value."""

    cleaned = value.strip().lower().replace("-", "_").removesuffix(".py")
    if not cleaned or cleaned in PACKAGE_ROOT_STOPWORDS:
        return None
    return cleaned


def _split_identifier_tokens(value: str) -> list[str]:
    """Split snake_case and CamelCase identifiers into normalized tokens."""

    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9]*", spaced.replace("_", " "))
    return [token.lower() for token in tokens if token]


def _split_text_tokens(value: str) -> list[str]:
    """Split free text into normalized tokens."""

    tokens = re.findall(r"[A-Za-z][A-Za-z0-9]*", value)
    return [token.lower() for token in tokens if token]
