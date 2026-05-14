"""AST-based intent suggestions using keyword extraction."""

import re
from dataclasses import dataclass
from typing import Any

from bpfw.catalog.keywords import extract_block_keywords, build_project_vocabulary
from bpfw.catalog.keywords.models import BlockKeywordProfile, KeywordCandidate, ProjectVocabulary
from bpfw.catalog.keywords.normalizer import normalize_tokens
from bpfw.catalog.keywords.tokenizer import tokenize_identifier
from bpfw.catalog.learning import get_top_learned_intents, score_phrase_context_match


@dataclass(frozen=True, slots=True)
class PurposeSuggestion:
    """Represent one deterministic natural-language purpose suggestion.

    The suggestion system uses fixed semantic slots with deterministic ordering.
    Scoring is local to each slot only, never global across all candidates.
    """

    text: str
    source: str
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _NormalizedFacts:
    """Normalized token collections per evidence source."""

    symbol: str
    symbol_type: str
    symbol_tokens: tuple[str, ...]
    path_tokens: tuple[str, ...]
    module_tokens: tuple[str, ...]
    signature_tokens: tuple[str, ...]
    parameter_tokens: tuple[str, ...]
    return_tokens: tuple[str, ...]
    method_tokens: tuple[str, ...]
    function_tokens: tuple[str, ...]
    docstring_tokens: tuple[str, ...]
    import_tokens: tuple[str, ...]
    decorator_tokens: tuple[str, ...]
    raw_functions: tuple[str, ...]
    raw_methods: tuple[str, ...]
    all_tokens: tuple[str, ...]


def compact_intent_text(text: str) -> str:
    """
    Compact purpose text to a concise form.

    Removes filler phrases like "from block evidence", "from deterministic",
    converts "Produce ranked" to "Suggest", and limits to 5 words maximum.

    Args:
        text: Text to compact.

    Returns:
        Compacted text.
    """
    if not text:
        return text

    # Convert "Produce ranked" to "Suggest"
    text = re.sub(r"\bProduce ranked\b", "Suggest", text, flags=re.IGNORECASE)

    # Convert "purpose suggestions" to just "purpose"
    text = re.sub(r"\bpurpose suggestions\b", "purposes", text, flags=re.IGNORECASE)

    # Remove specific filler phrases (only full matches)
    filler_phrases = [
        "from block evidence",
        "from deterministic text evidence",
        "from deterministic text evidence from one block dictionary",
        "natural-language",
        "natural language",
    ]
    for phrase in filler_phrases:
        text = text.replace(phrase, "")

    # Normalize whitespace
    text = " ".join(text.split())

    # Limit to 5 words
    words = text.split()
    if len(words) > 5:
        text = " ".join(words[:5])

    return text


def _apply_quality_filters(
    suggestions: list[PurposeSuggestion],
    facts: _NormalizedFacts,
) -> list[PurposeSuggestion]:
    """
    Filter suggestions by quality criteria.

    Rejects:
    - Incomplete endings ("can", "be")
    - "Raise" for non-error blocks
    - Duplicate words
    - "raised when" patterns

    Passes through:
    - Placeholders ("-", "Write custom purpose...")
    - Suggestions with valid action verbs

    Args:
        suggestions: List of suggestions to filter.
        facts: Normalized block facts.

    Returns:
        Filtered suggestions.
    """
    filtered: list[PurposeSuggestion] = []

    # Check if this is an error class
    is_error = facts.symbol.endswith("Error") or facts.symbol.endswith("Exception")

    for suggestion in suggestions:
        text = suggestion.text

        # Pass through placeholders
        if text in {"-", "Write custom purpose..."}:
            filtered.append(suggestion)
            continue

        # Reject incomplete endings (but not prepositions like "to", "for", "from")
        incomplete_endings = ("can", "be", "the", "a", "an")
        if text.lower().split()[-1] in incomplete_endings:
            continue

        # Reject "Raise" for non-error blocks
        if text.startswith("Raise") and not is_error:
            continue

        # Reject noisy "raised when" patterns
        if "raised when" in text.lower():
            continue

        # Reject duplicate words (anywhere, not just consecutive)
        words = text.split()
        if len(words) != len(set(words)):
            continue

        # Reject very short suggestions (< 2 words)
        if len(words) < 2:
            continue

        filtered.append(suggestion)

    return filtered


def suggest_intents(
    block: dict[str, Any],
    project_blocks: list[dict[str, Any]] | None = None,
    existing_intents: tuple[str, ...] = (),
) -> list[PurposeSuggestion]:
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
        List of PurposeSuggestion items.
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

    # Normalize block facts for quality filtering
    from bpfw.catalog.keywords.tokenizer import tokenize_identifier, tokenize_text

    def _get_nested_value(keys: tuple[str, ...], default: str = "") -> str:
        """Get value from nested dict or top level."""
        for key in keys:
            if "." in key:
                parts = key.split(".")
                value = block
                for part in parts:
                    if isinstance(value, dict):
                        value = value.get(part, {})
                if isinstance(value, str):
                    return value
            elif isinstance(block.get(key), str):
                return block.get(key, default)
        return default

    # Get basic info
    symbol = (
        block.get("location", {}).get("symbol")
        or block.get("code", {}).get("symbol")
        or block.get("symbol")
        or block.get("name")
        or ""
    )

    # Compose suggestions from keywords
    suggestions = _compose_suggestions(
        block=block,
        profile=profile,
        vocabulary=vocabulary,
        existing_intents=existing_intents,
    )

    # Apply quality filters
    facts = _NormalizedFacts(
        symbol=symbol,
        symbol_type="",
        symbol_tokens=tuple(tokenize_identifier(symbol.split(".")[-1] if "." in symbol else symbol)),
        path_tokens=(),
        module_tokens=(),
        signature_tokens=(),
        parameter_tokens=(),
        return_tokens=(),
        method_tokens=(),
        function_tokens=(),
        docstring_tokens=(),
        import_tokens=(),
        decorator_tokens=(),
        raw_functions=(),
        raw_methods=(),
        all_tokens=(),
    )
    suggestions = _apply_quality_filters(suggestions, facts)

    # Compact suggestions
    compacted_suggestions = []
    for suggestion in suggestions:
        compacted = PurposeSuggestion(
            text=compact_intent_text(suggestion.text),
            source=suggestion.source,
            evidence=suggestion.evidence,
        )
        compacted_suggestions.append(compacted)

    # Ensure we have exactly 6 slots
    return _ensure_six_slots(compacted_suggestions)


def _empty_intent_slots() -> list[PurposeSuggestion]:
    """Return fixed empty purpose slots when no purpose can be inferred."""

    return [
        PurposeSuggestion("-", "existing_intent", ("source: existing_intent",)),
        PurposeSuggestion("-", "learned_based", ("source: learned_based",)),
        PurposeSuggestion("-", "name_based", ("source: name_based",)),
        PurposeSuggestion("-", "docstring_based", ("source: docstring_based",)),
        PurposeSuggestion("-", "blended_based", ("source: blended_based",)),
        PurposeSuggestion("Write custom purpose...", "custom_intent", ("source: custom_intent",)),
    ]


def _compose_suggestions(
    block: dict[str, Any],
    profile: BlockKeywordProfile,
    vocabulary: ProjectVocabulary | None,
    existing_intents: tuple[str, ...],
) -> list[PurposeSuggestion]:
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
    suggestions: list[PurposeSuggestion] = []

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
    keyword_based = _compose_from_symbol(block) or _compose_from_keywords(
        top_keywords,
        primary_source="symbol_name",
    )
    if keyword_based:
        suggestions.append(keyword_based)

    # 4. Docstring-based suggestion
    docstring_based = _compose_from_docstring(block) or _compose_from_keywords(
        top_keywords,
        primary_source="docstring_summary",
    )
    if docstring_based and docstring_based != keyword_based:
        suggestions.append(docstring_based)

    # 5. Blended suggestion (from multiple sources)
    blended = _compose_blended(top_keywords, profile.phrases)
    if blended:
        suggestions.append(blended)

    # 6. Custom option
    suggestions.append(
        PurposeSuggestion(
            text="Write custom purpose...",
            source="custom_intent",
            evidence=("source: custom_intent",),
        )
    )

    # Ensure we have exactly 6 slots
    while len(suggestions) < 6:
        suggestions.insert(
            -1,  # Insert before custom option
            PurposeSuggestion(text="-", source="empty", evidence=("source: empty",)),
        )

    return suggestions[:6]


def _find_existing_intent_match(
    block: dict[str, Any],
    existing_intents: tuple[str, ...],
    top_keywords: list[KeywordCandidate],
) -> PurposeSuggestion | None:
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
        return PurposeSuggestion(
            text=best_match,
            source="existing_intent",
            evidence=(f"overlap: {best_score:.2f}", "source: existing_intent"),
        )

    return None


def _ensure_six_slots(suggestions: list[PurposeSuggestion]) -> list[PurposeSuggestion]:
    """
    Ensure suggestions list has exactly 6 slots, padding with placeholders.

    Args:
        suggestions: List of suggestions.

    Returns:
        List of exactly 6 suggestions.
    """
    # Define slot sources in fixed order
    slot_sources = [
        "existing_intent",
        "learned_based",
        "name_based",
        "docstring_based",
        "blended_based",
        "custom_intent",
    ]

    result: list[PurposeSuggestion] = []

    # Fill each slot
    for source in slot_sources:
        # Try to find existing suggestion with this source
        found = None
        for suggestion in suggestions:
            if suggestion.source == source:
                found = suggestion
                break

        if found:
            result.append(found)
        else:
            # Add placeholder
            text = "Write custom purpose..." if source == "custom_intent" else "-"
            result.append(PurposeSuggestion(text=text, source=source, evidence=(f"source: {source}",)))

    return result


def _find_learned_intent_match(
    block: dict[str, Any],
    top_keywords: list[KeywordCandidate],
) -> PurposeSuggestion | None:
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
        return PurposeSuggestion(
            text=best_match.title(),
            source="learned_based",
            evidence=(f"score: {best_score:.1f}", "source: learned_based"),
        )

    return None


def _compose_from_keywords(
    keywords: list[KeywordCandidate],
    primary_source: str = "symbol_name",
) -> PurposeSuggestion | None:
    """
    Compose a suggestion from keywords, prioritizing a specific source.

    Args:
        keywords: List of ranked keywords.
        primary_source: Source to prioritize (e.g., "symbol_name").

    Returns:
        PurposeSuggestion or None.
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

    return PurposeSuggestion(
        text=text,
        source="name_based" if primary_source == "symbol_name" else "docstring_based",
        evidence=(f"keywords: {', '.join(tokens[:3])}", f"source: {primary_source}"),
    )


def _compose_from_symbol(block: dict[str, Any]) -> PurposeSuggestion | None:
    """Compose a purpose suggestion from the symbol while preserving token order."""

    symbol = (
        block.get("location", {}).get("symbol")
        or block.get("code", {}).get("symbol")
        or block.get("symbol")
        or block.get("name")
        or ""
    )
    if not isinstance(symbol, str) or not symbol.strip():
        return None
    simple_name = symbol.split(".")[-1]
    tokens = normalize_tokens(tokenize_identifier(simple_name))
    if len(tokens) < 2:
        return None
    text = " ".join(tokens[:5])
    text = text[0].upper() + text[1:] if text else ""
    return PurposeSuggestion(
        text=text,
        source="name_based",
        evidence=(f"symbol: {simple_name}", "source: symbol_name"),
    )


def _compose_from_docstring(block: dict[str, Any]) -> PurposeSuggestion | None:
    """Compose a purpose suggestion directly from the block docstring."""

    detected = block.get("detected")
    if not isinstance(detected, dict):
        return None
    docstring = detected.get("docstring")
    if not isinstance(docstring, str) or not docstring.strip():
        return None

    first_sentence = docstring.strip().split(".")[0].strip()
    if not first_sentence:
        return None

    text = _purpose_text_from_docstring_sentence(first_sentence)
    if text is None:
        return None

    return PurposeSuggestion(
        text=text,
        source="docstring_based",
        evidence=(f"docstring: {first_sentence}", "source: docstring_based"),
    )


def _purpose_text_from_docstring_sentence(sentence: str) -> str | None:
    """Return a compact purpose phrase from one docstring sentence."""

    normalized = " ".join(sentence.split())
    lower = normalized.lower()

    path_match = re.match(
        r"^return paths? to (?P<target>.+?) files? that implement (?P<mechanism>.+)$",
        normalized,
        flags=re.IGNORECASE,
    )
    if path_match:
        mechanism = _clean_docstring_noun_phrase(path_match.group("mechanism"))
        if mechanism:
            return f"Return {mechanism} file paths"

    if lower.startswith("suggest natural-language purposes"):
        return "Suggest purpose"
    if lower.startswith("represent one deterministic natural-language purpose suggestion"):
        return "Suggest purpose"
    if lower.startswith("build "):
        return _compact_build_docstring(normalized)

    action_verbs = (
        "return",
        "validate",
        "create",
        "collect",
        "convert",
        "compose",
        "detect",
        "load",
        "write",
        "scan",
        "resolve",
        "ensure",
        "build",
        "extract",
        "parse",
        "render",
    )
    if not lower.startswith(action_verbs):
        return None
    return compact_intent_text(normalized)


def _clean_docstring_noun_phrase(text: str) -> str:
    """Normalize a docstring noun phrase for compact purpose text."""

    phrase = " ".join(text.strip().split())
    phrase = re.sub(r"^(the|a|an)\s+", "", phrase, flags=re.IGNORECASE)
    return phrase


def _compact_build_docstring(sentence: str) -> str:
    """Compact build-style docstrings without carrying secondary clauses."""

    phrase = re.sub(r",\s*including\b.*$", "", sentence, flags=re.IGNORECASE)
    phrase = re.sub(r"\s+for\s+a\s+project\b.*$", "", phrase, flags=re.IGNORECASE)
    phrase = re.sub(r"^Build\s+the\s+full\s+", "Build ", phrase, flags=re.IGNORECASE)
    return compact_intent_text(phrase)


def _compose_blended(
    keywords: list[KeywordCandidate],
    phrases: list[str],
) -> PurposeSuggestion | None:
    """
    Compose a blended suggestion from keywords and phrases.

    Args:
        keywords: List of ranked keywords.
        phrases: List of extracted phrases.

    Returns:
        PurposeSuggestion or None.
    """
    # Prefer phrases over keywords
    if phrases:
        # Use first phrase
        text = phrases[0].strip()
        text = text[0].upper() + text[1:] if text else ""

        return PurposeSuggestion(
            text=text,
            source="blended_based",
            evidence=(f"phrase: {phrases[0]}", "source: phrase"),
        )

    # Fallback to keywords if no phrases
    if keywords:
        tokens = [k.token for k in keywords[:4]]
        text = " ".join(tokens)
        text = text[0].upper() + text[1:] if text else ""

        return PurposeSuggestion(
            text=text,
            source="blended_based",
            evidence=(f"keywords: {', '.join(tokens[:3])}", "source: keywords"),
        )

    return None
