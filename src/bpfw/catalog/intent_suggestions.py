"""AST-based intent suggestions using keyword extraction."""

from dataclasses import dataclass
from typing import Any

from bpfw.catalog.keywords import extract_block_keywords, build_project_vocabulary
from bpfw.catalog.keywords.models import BlockKeywordProfile, KeywordCandidate, ProjectVocabulary
from bpfw.catalog.learning import get_top_learned_intents, score_phrase_context_match


@dataclass(frozen=True, slots=True)
class IntentSuggestion:
    """Represent one deterministic natural-language purpose suggestion."""

    text: str
    source: str
    evidence: tuple[str, ...]


def suggest_intents(
    block: dict[str, Any],
    project_blocks: list[dict[str, Any]] | None = None,
    existing_intents: tuple[str, ...] = (),
) -> list[IntentSuggestion]:
    """
    Suggest purposes using AST-extracted keywords.

    This implementation:
    - Extracts keywords from block using AST analysis
    - Uses project vocabulary to boost rare, distinctive tokens
    - Composes suggestions from keywords without hardcoded vocabulary

    Args:
        block: Block dictionary from scanner.
        project_blocks: Optional list of all blocks for vocabulary building.
        existing_intents: Existing purposes to consider for reuse.

    Returns:
        List of IntentSuggestion items.
    """
    # Build project vocabulary if blocks provided
    vocabulary = None
    if project_blocks:
        vocabulary = build_project_vocabulary(project_blocks)

    # Extract keywords from block
    profile = extract_block_keywords(block, vocabulary=vocabulary)

    # If no keywords found, return empty suggestions
    if not profile.keywords:
        return _empty_intent_slots()

    # Compose suggestions from keywords
    suggestions = _compose_suggestions(
        block=block,
        profile=profile,
        vocabulary=vocabulary,
        existing_intents=existing_intents,
    )

    return suggestions


def _empty_intent_slots() -> list[IntentSuggestion]:
    """Return fixed empty purpose slots when no purpose can be inferred."""

    return [
        IntentSuggestion("-", "existing_intent", ("source: existing_intent",)),
        IntentSuggestion("-", "learned_based", ("source: learned_based",)),
        IntentSuggestion("-", "keyword_based", ("source: keyword_based",)),
        IntentSuggestion("-", "docstring_based", ("source: docstring_based",)),
        IntentSuggestion("-", "blended_based", ("source: blended_based",)),
        IntentSuggestion("Write custom purpose...", "custom_intent", ("source: custom_intent",)),
    ]


def _compose_suggestions(
    block: dict[str, Any],
    profile: BlockKeywordProfile,
    vocabulary: ProjectVocabulary | None,
    existing_intents: tuple[str, ...],
) -> list[IntentSuggestion]:
    """
    Compose purpose suggestions from keyword profile.

    Args:
        block: Block dictionary.
        profile: Keyword profile for block.
        vocabulary: Optional project vocabulary.
        existing_intents: Existing purposes to consider.

    Returns:
        List of suggestions.
    """
    suggestions: list[IntentSuggestion] = []

    # Get top keywords
    top_keywords = profile.keywords[:10]

    # 1. Existing intent-based suggestion
    existing = _find_existing_intent_match(block, existing_intents, top_keywords)
    if existing:
        suggestions.append(existing)

    # 2. Learned-based suggestion
    learned = _find_learned_intent_match(block, top_keywords)
    if learned:
        suggestions.append(learned)

    # 3. Keyword-based suggestion (from symbol name)
    keyword_based = _compose_from_keywords(top_keywords, primary_source="symbol_name")
    if keyword_based:
        suggestions.append(keyword_based)

    # 4. Docstring-based suggestion
    docstring_based = _compose_from_keywords(top_keywords, primary_source="docstring_summary")
    if docstring_based and docstring_based != keyword_based:
        suggestions.append(docstring_based)

    # 5. Blended suggestion (from multiple sources)
    blended = _compose_blended(top_keywords, profile.phrases)
    if blended:
        suggestions.append(blended)

    # 6. Custom option
    suggestions.append(
        IntentSuggestion(
            text="Write custom purpose...",
            source="custom_intent",
            evidence=("source: custom_intent",),
        )
    )

    # Ensure we have exactly 6 slots
    while len(suggestions) < 6:
        suggestions.insert(
            -1,  # Insert before custom option
            IntentSuggestion(text="-", source="empty", evidence=("source: empty",)),
        )

    return suggestions[:6]


def _find_existing_intent_match(
    block: dict[str, Any],
    existing_intents: tuple[str, ...],
    top_keywords: list[KeywordCandidate],
) -> IntentSuggestion | None:
    """Find best matching existing intent from current blueprint."""

    if not existing_intents:
        return None

    # Build context from keywords
    context = " ".join(k.token for k in top_keywords)

    # Find best match
    best_match = ""
    best_score = 0

    for intent in existing_intents:
        # Score match using learning system
        overlap = score_phrase_context_match(intent, context)
        if overlap > best_score and overlap > 0.3:  # Minimum similarity threshold
            best_score = overlap
            best_match = intent

    if best_match:
        return IntentSuggestion(
            text=best_match,
            source="existing_intent",
            evidence=(f"overlap: {best_score:.2f}", "source: existing_intent"),
        )

    return None


def _find_learned_intent_match(
    block: dict[str, Any],
    top_keywords: list[KeywordCandidate],
) -> IntentSuggestion | None:
    """Find best matching intent from learning system."""

    # Get top learned intents
    learned = get_top_learned_intents(limit=10)

    if not learned:
        return None

    # Build context from keywords
    context = " ".join(k.token for k in top_keywords)

    # Find best match
    best_match = ""
    best_score = 0

    for text, count in learned:
        overlap = score_phrase_context_match(text, context)
        score = overlap * 10 + min(count, 8)
        if score > best_score and overlap > 0.2:  # Minimum similarity threshold
            best_score = score
            best_match = text

    if best_match:
        return IntentSuggestion(
            text=best_match.title(),
            source="learned_based",
            evidence=(f"score: {best_score:.1f}", "source: learned_based"),
        )

    return None


def _compose_from_keywords(
    keywords: list[KeywordCandidate],
    primary_source: str = "symbol_name",
) -> IntentSuggestion | None:
    """
    Compose a suggestion from keywords, prioritizing a specific source.

    Args:
        keywords: List of ranked keywords.
        primary_source: Source to prioritize (e.g., "symbol_name").

    Returns:
        IntentSuggestion or None.
    """
    # Filter keywords by primary source
    primary_keywords = [k for k in keywords if primary_source in k.sources]

    # If no keywords from primary source, use top keywords
    source_keywords = primary_keywords if primary_keywords else keywords[:5]

    if not source_keywords:
        return None

    # Build suggestion from top 3-5 keywords
    tokens = [k.token for k in source_keywords[:5]]

    # Skip if too few tokens
    if len(tokens) < 2:
        return None

    # Capitalize first letter
    text = " ".join(tokens)
    text = text[0].upper() + text[1:] if text else ""

    return IntentSuggestion(
        text=text,
        source="keyword_based" if primary_source == "symbol_name" else "docstring_based",
        evidence=(f"keywords: {', '.join(tokens[:3])}", f"source: {primary_source}"),
    )


def _compose_blended(
    keywords: list[KeywordCandidate],
    phrases: list[str],
) -> IntentSuggestion | None:
    """
    Compose a blended suggestion from keywords and phrases.

    Args:
        keywords: List of ranked keywords.
        phrases: List of extracted phrases.

    Returns:
        IntentSuggestion or None.
    """
    # Prefer phrases over keywords
    if phrases:
        # Use first phrase
        text = phrases[0].strip()
        text = text[0].upper() + text[1:] if text else ""

        return IntentSuggestion(
            text=text,
            source="blended_based",
            evidence=(f"phrase: {phrases[0]}", "source: phrase"),
        )

    # Fallback to keywords if no phrases
    if keywords:
        tokens = [k.token for k in keywords[:4]]
        text = " ".join(tokens)
        text = text[0].upper() + text[1:] if text else ""

        return IntentSuggestion(
            text=text,
            source="blended_based",
            evidence=(f"keywords: {', '.join(tokens[:3])}", "source: keywords"),
        )

    return None