"""AST-based domain suggestions using path and vocabulary analysis."""

from dataclasses import dataclass
from typing import Any

from bpfw.catalog.keywords import build_project_vocabulary
from bpfw.catalog.keywords.models import ProjectVocabulary
from bpfw.catalog.keywords.tokenizer import tokenize_identifier
from bpfw.catalog.learning import load_learning_scores
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
) -> list[DomainSuggestion]:
    """
    Suggest domains using path analysis and vocabulary.

    This implementation:
    - Analyzes file path structure to find domain clues
    - Uses project vocabulary to identify generic vs distinctive tokens
    - Boosts domains that appear in path but are rare in project

    Args:
        block: Block dictionary from scanner.
        project_blocks: Optional list of all blocks for vocabulary building.

    Returns:
        List of DomainSuggestion items.
    """
    # Build project vocabulary if blocks provided
    vocabulary = None
    if project_blocks:
        vocabulary = build_project_vocabulary(project_blocks)

    # Collect evidence from block
    evidence = _collect_domain_evidence(block)

    # Compose and rank candidates
    candidates = _compose_domain_candidates(evidence, vocabulary)

    return _rank_domain_suggestions(candidates)


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


def _compose_domain_candidates(
    evidence: _DomainEvidence,
    vocabulary: ProjectVocabulary | None,
) -> list[DomainSuggestion]:
    """Compose domain candidates from normalized block evidence."""

    candidates: list[DomainSuggestion] = []

    # Extract folder tokens (excluding file name)
    folder_tokens = [
        token
        for part in evidence.path_parts[:-1]
        for token in part.split("_")
        if token and token not in TECHNICAL_STOPWORDS
    ]

    # Extract file stem tokens
    file_tokens = []
    if evidence.file_stem:
        file_tokens = [t for t in evidence.file_stem.split("_") if t and t not in TECHNICAL_STOPWORDS]

    # Extract module tokens
    module_tokens = [part for part in evidence.module_parts if part and part not in TECHNICAL_STOPWORDS]

    # Extract symbol tokens (excluding generics based on vocabulary)
    symbol_tokens = []
    for token in evidence.symbol_tokens:
        if token in TECHNICAL_STOPWORDS:
            continue
        # Filter out generic tokens if vocabulary available
        if vocabulary and vocabulary.is_common_token(token, threshold=0.7):
            continue
        symbol_tokens.append(token)

    # Extract docstring tokens (excluding generics)
    docstring_tokens = []
    for token in evidence.docstring_tokens:
        if token in TECHNICAL_STOPWORDS:
            continue
        if vocabulary and vocabulary.is_common_token(token, threshold=0.7):
            continue
        docstring_tokens.append(token)

    # Build sets for overlap detection
    symbol_set = set(symbol_tokens)
    docstring_set = set(docstring_tokens)
    path_set = set(folder_tokens + file_tokens)
    module_set = set(module_tokens)

    # 1. Folder-based candidates (highest priority)
    for token in set(folder_tokens):
        score = 40
        evidence_lines = [f"folder: {token}"]

        # Boost if token appears in symbol
        if token in symbol_set:
            score += 25
            evidence_lines.append("symbol overlap")

        # Boost if token appears in module
        if token in module_set:
            score += 20
            evidence_lines.append("module overlap")

        # Boost if token is rare in project
        if vocabulary:
            frequency = vocabulary.get_token_block_frequency(token)
            if frequency < 0.3:  # Rare token
                score += 15
                evidence_lines.append(f"rare token ({frequency:.2f})")

        _append_candidate(candidates, token, score, tuple(evidence_lines))

    # 2. File stem candidates
    for token in set(file_tokens):
        score = 35
        evidence_lines = [f"file: {token}"]

        # Boost if token appears in symbol
        if token in symbol_set:
            score += 15
            evidence_lines.append("symbol overlap")

        # Boost if token is rare
        if vocabulary:
            frequency = vocabulary.get_token_block_frequency(token)
            if frequency < 0.3:
                score += 10
                evidence_lines.append(f"rare token ({frequency:.2f})")

        _append_candidate(candidates, token, score, tuple(evidence_lines))

    # 3. Module-based candidates
    for token in set(module_tokens):
        score = 30
        evidence_lines = [f"module: {token}"]

        # Boost if token appears in symbol
        if token in symbol_set:
            score += 20
            evidence_lines.append("symbol overlap")

        # Boost if token appears in path
        if token in path_set:
            score += 15
            evidence_lines.append("path overlap")

        _append_candidate(candidates, token, score, tuple(evidence_lines))

    # 4. Symbol-based candidates (lower priority, only if distinctive)
    for token in set(symbol_tokens):
        score = 25
        evidence_lines = [f"symbol: {token}"]

        # Boost if token appears in docstring
        if token in docstring_set:
            score += 15
            evidence_lines.append("docstring overlap")

        # Boost if token appears in path/module
        if token in path_set or token in module_set:
            score += 20
            evidence_lines.append("path/module overlap")

        # Only add if token is distinctive (rare) or appears in multiple places
        has_path_overlap = token in path_set or token in module_set
        has_docstring_overlap = token in docstring_set

        if not (has_path_overlap or has_docstring_overlap):
            # Check if rare in project
            is_rare = False
            if vocabulary:
                frequency = vocabulary.get_token_block_frequency(token)
                is_rare = frequency < 0.2

            if not is_rare:
                # Skip generic symbols that don't appear elsewhere
                continue

        _append_candidate(candidates, token, score, tuple(evidence_lines))

    return candidates


def _rank_domain_suggestions(candidates: list[DomainSuggestion]) -> list[DomainSuggestion]:
    """Rank, deduplicate, and limit domain suggestions."""

    # Load learning scores for boosts
    learning_scores = load_learning_scores().domain_boost

    # Deduplicate by text, keeping highest score
    by_text: dict[str, DomainSuggestion] = {}
    for candidate in candidates:
        normalized = candidate.text.strip().lower()
        if not normalized:
            continue

        # Apply learning boost
        learned_boost = min(12, learning_scores.get(normalized, 0) * 2)
        boosted_score = candidate.score + learned_boost

        existing = by_text.get(normalized)
        if existing is None or boosted_score > existing.score:
            evidence = candidate.evidence
            if learned_boost:
                evidence = candidate.evidence + (f"learned_boost:{learned_boost}",)
            by_text[normalized] = DomainSuggestion(
                text=normalized,
                score=boosted_score,
                evidence=evidence,
            )

    # Sort by score (descending), then by length (shorter first), then by text
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
    """Append one candidate if value is valid."""

    if text is None:
        return

    cleaned = text.strip().lower().replace("-", "_")
    if not cleaned:
        return

    if cleaned in TECHNICAL_STOPWORDS:
        return

    if cleaned.endswith(".py"):
        cleaned = cleaned[:-3]

    if not cleaned:
        return

    candidates.append(DomainSuggestion(text=cleaned, score=score, evidence=evidence))


def _tokenize_text(text: str) -> list[str]:
    """Tokenize free text into words."""

    import re

    tokens = re.findall(r"[A-Za-z][A-Za-z0-9]*", text)
    return [token.lower() for token in tokens if token]