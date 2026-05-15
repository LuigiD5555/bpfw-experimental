"""Deterministic purpose suggestions with fixed semantic slots."""

import re
from dataclasses import dataclass
from typing import Any

from bpfw.catalog.keywords import extract_block_keywords, build_project_vocabulary
from bpfw.catalog.keywords.models import BlockKeywordProfile, KeywordCandidate, ProjectVocabulary
from bpfw.catalog.keywords.normalizer import normalize_tokens
from bpfw.catalog.keywords.tokenizer import tokenize_identifier
from bpfw.catalog.learning import get_top_learned_purposes, score_phrase_context_match


@dataclass(frozen=True, slots=True)
class PurposeSuggestion:
    """Represent one deterministic natural-language purpose suggestion.

    The suggestion system uses fixed semantic slots with deterministic ordering.
    Scoring is local to each slot only, never global across all candidates.
    
    Slot order (fixed, never changes):
    1. Existing/similar purpose - reuse from current blueprint
    2. Learned/contextual purpose - from learning system
    3. Name-based purpose - from symbol name tokens
    4. Docstring-based purpose - from docstring summary
    5. Blended-based purpose - from multiple sources
    6. Custom purpose - user-provided
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


def compact_purpose_text(text: str) -> str:
    """
    Compact purpose text to a concise form.

    Removes filler phrases like "from block evidence" and limits to 5 words maximum.

    Args:
        text: Text to compact.

    Returns:
        Compacted text.
    """
    if not text:
        return text

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

    return text.lower()


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
    - Placeholders ("-", "write custom purpose...")
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
        if text in {"-", "write custom purpose..."}:
            filtered.append(suggestion)
            continue

        words = text.lower().split()

        # Reject incomplete beginnings and endings.
        incomplete_beginnings = ("when", "while", "is", "are", "the", "a", "an", "of")
        if words[0] in incomplete_beginnings:
            continue

        incomplete_endings = ("can", "be", "the", "a", "an")
        if words[-1] in incomplete_endings:
            continue

        # Reject "Raise" for non-error blocks
        if text.lower().startswith("raise") and not is_error:
            continue

        # Reject noisy "raised when" patterns
        if "raised when" in text.lower():
            continue

        # Reject duplicate words (anywhere, not just consecutive)
        original_words = text.split()
        if len(original_words) != len(set(original_words)):
            continue

        # Reject very short suggestions (< 2 words)
        if len(words) < 2:
            continue

        filtered.append(suggestion)

    return filtered


def suggest_purposes(
    block: dict[str, Any],
    project_blocks: list[dict[str, Any]] | None = None,
    existing_purposes: tuple[str, ...] = (),
) -> list[PurposeSuggestion]:
    """
    Suggest purposes using AST-extracted keywords.

    This implementation extracts block evidence and fills six fixed slots.
    Evidence may be compared inside one slot, but slots are never sorted or
    reordered dynamically.

    Args:
        block: Block dictionary from scanner.
        project_blocks: Optional list of all blocks for vocabulary building.
        existing_purposes: Existing purposes to consider for reuse.

    Returns:
        List of PurposeSuggestion items in fixed slot order.
    """
    # Build project vocabulary if blocks provided
    vocabulary = None
    if project_blocks:
        vocabulary = build_project_vocabulary(project_blocks)

    # Extract keywords from block
    profile = extract_block_keywords(block, vocabulary=vocabulary)

    # Normalize block facts for quality filtering
    from bpfw.catalog.keywords.tokenizer import tokenize_identifier

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
        docstring_tokens=tuple(_tokenize_purpose_text(
            block.get("detected", {}).get("docstring", "")
            if isinstance(block.get("detected"), dict) else ""
        )),
        import_tokens=(),
        decorator_tokens=(),
        raw_functions=(),
        raw_methods=(),
        all_tokens=(),
    )
    suggestions = _compose_suggestions(
        block=block,
        profile=profile,
        vocabulary=vocabulary,
        existing_purposes=existing_purposes,
        facts=facts,
    )
    return _ensure_six_slots(suggestions)


def _tokenize_purpose_text(text: str) -> list[str]:
    """Tokenize natural-language purpose evidence into normalized tokens."""

    if not isinstance(text, str):
        return []
    return normalize_tokens(re.findall(r"[A-Za-z][A-Za-z0-9]*", text))


def _empty_purpose_slots() -> list[PurposeSuggestion]:
    """Return fixed empty purpose slots when no purpose can be inferred."""

    return [
        PurposeSuggestion("-", "existing_purpose", ("source: existing_purpose",)),
        PurposeSuggestion("-", "learned_based", ("source: learned_based",)),
        PurposeSuggestion("-", "name_based", ("source: name_based",)),
        PurposeSuggestion("-", "docstring_based", ("source: docstring_based",)),
        PurposeSuggestion("-", "blended_based", ("source: blended_based",)),
        PurposeSuggestion("write custom purpose...", "custom_purpose", ("source: custom_purpose",)),
    ]


def _compose_suggestions(
    block: dict[str, Any],
    profile: BlockKeywordProfile,
    vocabulary: ProjectVocabulary | None,
    existing_purposes: tuple[str, ...],
    facts: _NormalizedFacts,
) -> list[PurposeSuggestion]:
    """Compose purpose suggestions in fixed semantic slot order."""

    top_keywords = profile.keywords[:10]
    existing = _find_existing_purpose_match(block, existing_purposes, top_keywords)
    learned = _find_learned_purpose_match(block, top_keywords)
    name_based = _compose_from_symbol(block)
    docstring_based = _compose_from_docstring(block, facts)
    blended = _compose_blended(
        block=block,
        keywords=top_keywords,
        phrases=profile.phrases,
        facts=facts,
        learned_suggestion=learned,
        previous_suggestions=tuple(
            suggestion.text
            for suggestion in (existing, learned, name_based, docstring_based)
            if suggestion is not None
        ),
    )

    return [
        _placeholder("existing_purpose") if existing is None else existing,
        _placeholder("learned_based") if learned is None else learned,
        _placeholder("name_based") if name_based is None else name_based,
        _placeholder("docstring_based") if docstring_based is None else docstring_based,
        _placeholder("blended_based") if blended is None else blended,
        PurposeSuggestion(
            text="write custom purpose...",
            source="custom_purpose",
            evidence=("source: custom_purpose",),
        ),
    ]


def _placeholder(source: str) -> PurposeSuggestion:
    """Return an empty fixed-slot placeholder."""

    return PurposeSuggestion(text="-", source=source, evidence=(f"source: {source}",))


def _is_placeholder_text(text: str) -> bool:
    """Return True when text is an inspector placeholder, not a real value."""

    normalized = " ".join(text.strip().lower().split())
    return normalized in {"", "-", "write custom purpose", "write custom purpose..."}


def _normalize_purpose_output_text(text: str) -> str:
    """Return suggestion text in the canonical lowercase display form."""

    normalized = " ".join(text.strip().split())
    normalized_lower = normalized.lower()
    if normalized_lower in {"", "-"}:
        return "-"
    if normalized_lower in {"write custom purpose", "write custom purpose..."}:
        return "write custom purpose..."
    return normalized_lower


def _with_normalized_purpose_text(suggestion: PurposeSuggestion) -> PurposeSuggestion:
    """Return a copy of one suggestion with canonical lowercase text."""

    return PurposeSuggestion(
        text=_normalize_purpose_output_text(suggestion.text),
        source=suggestion.source,
        evidence=suggestion.evidence,
    )


def _finalize_suggestion(
    text: str,
    source: str,
    evidence: tuple[str, ...],
    facts: _NormalizedFacts,
) -> PurposeSuggestion | None:
    """Compact and validate one slot suggestion without reordering slots."""

    compacted = compact_purpose_text(text)
    candidate = PurposeSuggestion(text=compacted, source=source, evidence=evidence)
    filtered = _apply_quality_filters([candidate], facts)
    if not filtered:
        return None
    if _is_placeholder_text(filtered[0].text):
        return None
    return filtered[0]


def _find_existing_purpose_match(
    block: dict[str, Any],
    existing_purposes: tuple[str, ...],
    top_keywords: list[KeywordCandidate],
) -> PurposeSuggestion | None:
    """Find a stable matching existing purpose from current blueprint."""

    current_purpose = block.get("purpose")
    context = " ".join(k.token for k in top_keywords)
    for purpose in existing_purposes:
        if not isinstance(purpose, str) or _is_placeholder_text(purpose):
            continue
        if isinstance(current_purpose, str) and purpose.strip() == current_purpose.strip():
            continue
        overlap = score_phrase_context_match(purpose, context)
        if overlap >= 2:
            return PurposeSuggestion(
                text=purpose,
                source="existing_purpose",
                evidence=(f"overlap: {overlap}", "source: existing_purpose"),
            )
    return None


def _ensure_six_slots(suggestions: list[PurposeSuggestion]) -> list[PurposeSuggestion]:
    """
    Ensure suggestions list has exactly 6 slots in fixed order, padding with placeholders.

    Slot order is deterministic and never changes:
    1. existing_purpose
    2. learned_based
    3. name_based
    4. docstring_based
    5. blended_based
    6. custom_purpose

    Args:
        suggestions: List of suggestions.

    Returns:
        List of exactly 6 suggestions in fixed slot order.
    """
    # Define slot sources in fixed order
    slot_sources = [
        "existing_purpose",
        "learned_based",
        "name_based",
        "docstring_based",
        "blended_based",
        "custom_purpose",
    ]

    result: list[PurposeSuggestion] = []
    seen_texts: set[str] = set()

    for source in slot_sources:
        found = None
        for suggestion in suggestions:
            if suggestion.source == source:
                found = suggestion
                break

        if found is None:
            text = "write custom purpose..." if source == "custom_purpose" else "-"
            result.append(PurposeSuggestion(text=text, source=source, evidence=(f"source: {source}",)))
            continue

        found = _with_normalized_purpose_text(found)
        normalized_text = " ".join(found.text.strip().lower().split())
        if (
            source != "custom_purpose"
            and normalized_text not in {"", "-"}
            and normalized_text in seen_texts
        ):
            result.append(PurposeSuggestion(text="-", source=source, evidence=(f"source: {source}",)))
            continue

        if normalized_text not in {"", "-"}:
            seen_texts.add(normalized_text)
        result.append(found)

    return result


def _find_learned_purpose_match(
    block: dict[str, Any],
    top_keywords: list[KeywordCandidate],
) -> PurposeSuggestion | None:
    """Find a learned purpose only when context overlap is strong."""

    learned = get_top_learned_purposes(limit=20)
    if not learned:
        return None

    generic_tokens = {
        "resolve", "handle", "process", "build", "create", "make", "run",
        "load", "save", "write", "read", "get", "set", "update", "manage",
    }
    context_tokens = {k.token for k in top_keywords if k.token not in generic_tokens}
    context = " ".join(context_tokens)
    if len(context_tokens) < 2:
        return None

    for text, _count in learned:
        overlap = score_phrase_context_match(text, context)
        if overlap >= 2:
            return PurposeSuggestion(
                text=text,
                source="learned_based",
                evidence=(f"overlap: {overlap}", "source: learned_based"),
            )
    return None


def _compose_from_keywords(
    keywords: list[KeywordCandidate],
    primary_source: str = "symbol_name",
) -> PurposeSuggestion | None:
    """
    Compose a suggestion from keywords, prioritizing a specific source.

    Scoring is local to this slot only, not global.

    Args:
        keywords: List of keyword candidates.
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
    if _is_error_symbol(simple_name):
        text = "raise " + " ".join(tokens[:4])
    else:
        text = " ".join(tokens[:5])
    text = text[0].upper() + text[1:] if text else ""
    return PurposeSuggestion(
        text=compact_purpose_text(text),
        source="name_based",
        evidence=(f"symbol: {simple_name}", "source: symbol_name"),
    )


def _is_error_symbol(symbol: str) -> bool:
    """Return True when symbol names an error or exception class."""

    return symbol.endswith("Error") or symbol.endswith("Exception")


def _compose_from_docstring(block: dict[str, Any], facts: _NormalizedFacts) -> PurposeSuggestion | None:
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

    text = _purpose_text_from_docstring_sentence(first_sentence, facts)
    if text is None:
        return None

    return _finalize_suggestion(
        text=text,
        source="docstring_based",
        evidence=(f"docstring: {first_sentence}", "source: docstring_based"),
        facts=facts,
    )


def _purpose_text_from_docstring_sentence(
    sentence: str,
    facts: _NormalizedFacts,
) -> str | None:
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
        return "Represent purpose suggestion"
    if lower.startswith("build "):
        return _compact_build_docstring(normalized)

    represent_result = _compact_represent_result_docstring(normalized)
    if represent_result:
        return represent_result

    passive_patterns = (
        ("raised when", "Raise"),
        ("provides", "Provide"),
        ("stores", "Store"),
        ("represents", "Represent"),
        ("defines", "Define"),
        ("handles", "Handle"),
    )
    for prefix, action in passive_patterns:
        if lower.startswith(prefix):
            remainder = normalized[len(prefix):].strip()
            phrase = _clean_docstring_noun_phrase(remainder)
            if prefix == "raised when":
                phrase = _normalize_raised_when_phrase(phrase)
                if not phrase:
                    return None
                return f"{action} {phrase}"
            return f"{action} {phrase}" if phrase else None

    action_verbs = (
        "return", "validate", "create", "collect", "convert", "compose",
        "detect", "load", "write", "scan", "resolve", "ensure", "build",
        "extract", "parse", "render", "provide", "store", "represent",
        "define", "handle", "raise",
    )
    if not lower.startswith(action_verbs):
        return None
    return compact_purpose_text(normalized)


def _compact_represent_result_docstring(sentence: str) -> str | None:
    """Compact represent-result docstrings into an active purpose phrase."""

    match = re.match(
        r"^represent\s+the\s+result\s+of\s+(?:a|an|the)?\s*(?P<context>.+)$",
        sentence,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    context = re.sub(r"\boperations?\b\.?$", "", match.group("context"), flags=re.IGNORECASE)
    tokens = [
        token
        for token in _tokenize_purpose_text(context)
        if token not in {"bpfw", "operation", "operations"}
    ]
    if not tokens:
        return None
    tokens = tokens[:3]
    if tokens[-1] != "result":
        tokens.append("result")
    return "Represent " + " ".join(tokens[:4])


def _normalize_raised_when_phrase(phrase: str) -> str:
    """Convert a raised-when clause into an error purpose object."""

    cleaned = re.sub(r"\bis attempted\b", "", phrase, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bwhile\b.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bwhen\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = _clean_docstring_noun_phrase(cleaned)
    tokens = normalize_tokens(tokenize_identifier(cleaned))
    filtered = [token for token in tokens if token not in {"is", "are", "was", "were"}]
    if not filtered:
        return ""
    if filtered[-1] not in {"error", "exception"}:
        filtered.append("error")
    return " ".join(filtered[:4])


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
    return compact_purpose_text(phrase)


_BLENDED_ACTIONS = {
    "build": "Build",
    "collect": "Collect",
    "compose": "Compose",
    "convert": "Convert",
    "create": "Create",
    "declare": "Declare",
    "define": "Define",
    "detect": "Detect",
    "extract": "Extract",
    "handle": "Handle",
    "load": "Load",
    "lock": "Lock",
    "normalize": "Normalize",
    "parse": "Parse",
    "protect": "Protect",
    "raise": "Raise",
    "raised": "Raise",
    "read": "Read",
    "render": "Render",
    "represent": "Represent",
    "resolve": "Resolve",
    "return": "Return",
    "save": "Save",
    "scan": "Scan",
    "store": "Store",
    "suggest": "Suggest",
    "validate": "Validate",
    "verify": "Verify",
    "write": "Write",
}

_BLENDED_KIND_TOKENS = {
    "class",
    "clas",
    "dataclass",
    "function",
    "method",
    "module",
    "object",
}

_BLENDED_STATE_TOKENS = {
    "active",
    "cached",
    "deprecated",
    "duplicate",
    "experimental",
    "external",
    "forbidden",
    "internal",
    "invalid",
    "legacy",
    "locked",
    "missing",
    "protected",
    "unauthorized",
    "unknown",
}

_BLENDED_GLUE_TOKENS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "by",
    "can",
    "for",
    "from",
    "in",
    "into",
    "bpfw",
    "is",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "when",
    "while",
    "with",
}

_BLENDED_PROCEDURAL_TOKENS = {
    "attempt",
    "attempted",
    "operation",
    "operations",
    "requires",
    "require",
    "required",
    "used",
    "using",
}

_BLENDED_OPERATION_TOKENS = {
    "build",
    "collect",
    "compose",
    "convert",
    "create",
    "detect",
    "extract",
    "load",
    "parse",
    "read",
    "render",
    "resolve",
    "return",
    "save",
    "scan",
    "store",
    "validate",
    "verify",
    "write",
}

_BLENDED_TERMINAL_KIND_TOKENS = {"error", "exception", "result", "config", "resource"}


def _compose_blended(
    block: dict[str, Any],
    keywords: list[KeywordCandidate],
    phrases: list[str],
    facts: _NormalizedFacts,
    learned_suggestion: PurposeSuggestion | None = None,
    previous_suggestions: tuple[str, ...] = (),
) -> PurposeSuggestion | None:
    """Compose a blended suggestion by following deterministic evidence routes."""

    candidates: list[tuple[str, tuple[str, ...]]] = []

    learned_candidate = _compose_blended_from_learned(learned_suggestion, facts)
    if learned_candidate:
        candidates.append((learned_candidate, ("source: blended_learned_context",)))

    docstring_symbol_candidate = _compose_blended_from_docstring_and_symbol(facts)
    if docstring_symbol_candidate:
        candidates.append((docstring_symbol_candidate, ("source: blended_docstring_symbol",)))

    docstring_action_symbol_candidate = _compose_blended_from_docstring_action_and_symbol(facts)
    if docstring_action_symbol_candidate:
        candidates.append((docstring_action_symbol_candidate, ("source: blended_docstring_action_symbol",)))

    symbol_context_candidate = _compose_blended_from_symbol_context(block, facts)
    if symbol_context_candidate:
        candidates.append((symbol_context_candidate, ("source: blended_symbol_context",)))

    for phrase in phrases:
        if phrase.strip():
            candidates.append((phrase.strip(), (f"phrase: {phrase}", "source: phrase")))

    keyword_candidate = _compose_blended_from_keywords(keywords)
    if keyword_candidate:
        candidates.append((keyword_candidate, ("source: keywords",)))

    previous_normalized = {
        " ".join(text.lower().split())
        for text in previous_suggestions
        if not _is_placeholder_text(text)
    }
    seen: set[str] = set()
    deferred_duplicate: PurposeSuggestion | None = None

    for text, evidence in candidates:
        normalized = " ".join(text.lower().split())
        if normalized in seen:
            continue
        seen.add(normalized)
        suggestion = _finalize_suggestion(text, "blended_based", evidence, facts)
        if suggestion is None:
            continue
        suggestion_normalized = " ".join(suggestion.text.lower().split())
        if suggestion_normalized in previous_normalized:
            if deferred_duplicate is None:
                deferred_duplicate = suggestion
            continue
        return suggestion

    return deferred_duplicate


def _compose_blended_from_learned(
    learned_suggestion: PurposeSuggestion | None,
    facts: _NormalizedFacts,
) -> str | None:
    """Blend a aligned learned phrase with current symbol and docstring evidence."""

    if learned_suggestion is None or _is_placeholder_text(learned_suggestion.text):
        return None
    learned_tokens = _tokenize_blended_text(learned_suggestion.text, facts)
    context_tokens = _current_blended_context_tokens(facts)
    if not _learned_tokens_are_aligned(learned_tokens, context_tokens):
        return None

    action = _first_blended_action(learned_tokens)
    if action is None:
        return None

    object_tokens = _build_blended_object_from_context(facts, include_operation=False)
    if not object_tokens:
        object_tokens = _object_tokens_from_blended_tokens(learned_tokens)
    if not object_tokens:
        return None

    return f"{action} {' '.join(object_tokens[:4])}"


def _compose_blended_from_docstring_and_symbol(facts: _NormalizedFacts) -> str | None:
    """Build blended text from docstring context and symbol tokens."""

    if not facts.docstring_tokens and not facts.symbol_tokens:
        return None

    if _is_error_symbol(facts.symbol):
        if _has_token(facts.docstring_tokens, "protected") and _has_any_token(facts.docstring_tokens, {"lock", "locked"}):
            object_tokens = _build_lock_object_tokens(facts)
            if object_tokens:
                return f"Protect {' '.join(object_tokens[:4])}"
        object_tokens = _build_blended_object_from_context(facts, include_operation=True)
        if object_tokens:
            return f"Handle {' '.join(object_tokens[:4])}"

    action = _first_blended_action(facts.docstring_tokens)
    object_tokens = _build_blended_object_from_context(facts, include_operation=True)
    if action and object_tokens:
        return f"{action} {' '.join(object_tokens[:4])}"
    return None


def _compose_blended_from_docstring_action_and_symbol(facts: _NormalizedFacts) -> str | None:
    """Build a blended candidate from docstring action and symbol object only."""

    action = _first_blended_action(facts.docstring_tokens)
    object_tokens = _object_tokens_from_blended_tokens(list(facts.symbol_tokens))
    if action and object_tokens:
        return f"{action} {' '.join(object_tokens[:4])}"
    return None


def _compose_blended_from_symbol_context(
    block: dict[str, Any],
    facts: _NormalizedFacts,
) -> str | None:
    """Build a conservative blended candidate from symbol-derived text."""

    symbol_suggestion = _compose_from_symbol(block)
    if symbol_suggestion is None:
        return None
    return symbol_suggestion.text


def _compose_blended_from_keywords(keywords: list[KeywordCandidate]) -> str | None:
    """Build a final blended fallback from ordered keyword evidence."""

    if not keywords:
        return None
    tokens = [k.token for k in keywords[:5]]
    action = _infer_action_from_tokens(tuple(tokens))
    if action:
        rest = [token for token in tokens if token != action.lower()]
        if rest:
            return f"{action} {' '.join(rest[:4])}"
    if len(tokens) >= 2:
        return " ".join(tokens[:5])
    return None


def _tokenize_blended_text(text: str, facts: _NormalizedFacts) -> list[str]:
    """Tokenize blended evidence and split glued learned symbol tokens when possible."""

    tokens: list[str] = []
    symbol_joined = "".join(facts.symbol_tokens)
    for raw_token in re.findall(r"[A-Za-z][A-Za-z0-9]*", text):
        normalized_parts = normalize_tokens(tokenize_identifier(raw_token))
        for normalized_part in normalized_parts:
            if normalized_part == symbol_joined and facts.symbol_tokens:
                tokens.extend(facts.symbol_tokens)
                continue
            tokens.extend(_expand_known_blended_token(normalized_part, facts))
    return tokens


def _expand_known_blended_token(token: str, facts: _NormalizedFacts) -> list[str]:
    """Expand compact learned tokens using current symbol evidence."""

    if token == "clas":
        return ["class"]
    if token in facts.symbol_tokens:
        return [token]
    for suffix in ("exception", "error"):
        if token.endswith(suffix) and len(token) > len(suffix):
            root = token[: -len(suffix)]
            expanded_root = _split_root_with_symbol_tokens(root, facts.symbol_tokens)
            return expanded_root + [suffix]
    return [token]


def _split_root_with_symbol_tokens(root: str, symbol_tokens: tuple[str, ...]) -> list[str]:
    """Split a glued token root when current symbol tokens explain it."""

    if not symbol_tokens:
        return [root]
    result: list[str] = []
    remaining = root
    for symbol_token in symbol_tokens:
        if not remaining:
            break
        if remaining.startswith(symbol_token):
            result.append(symbol_token)
            remaining = remaining[len(symbol_token):]
    if remaining:
        result.append(remaining)
    return result or [root]


def _current_blended_context_tokens(facts: _NormalizedFacts) -> set[str]:
    """Return functional tokens from symbol and docstring evidence."""

    return {
        token
        for token in tuple(facts.symbol_tokens) + tuple(facts.docstring_tokens)
        if _is_functional_blended_token(token)
    }


def _learned_tokens_are_aligned(
    learned_tokens: list[str],
    context_tokens: set[str],
) -> bool:
    """Return True when learned evidence matches at least two current tokens."""

    learned_functional = {
        token for token in learned_tokens if _is_functional_blended_token(token)
    }
    return len(learned_functional & context_tokens) >= 2


def _first_blended_action(tokens: tuple[str, ...] | list[str]) -> str | None:
    """Return the first action token in source order."""

    for token in tokens:
        action = _BLENDED_ACTIONS.get(token)
        if action:
            return action
    return None


def _build_blended_object_from_context(
    facts: _NormalizedFacts,
    include_operation: bool,
) -> list[str]:
    """Build object tokens from symbol first, enriched by docstring modifiers."""

    symbol_object = _object_tokens_from_blended_tokens(list(facts.symbol_tokens))
    modifiers = _docstring_modifier_tokens(facts)
    doc_objects = _docstring_object_tokens(facts, include_operation=include_operation)

    result = _enrich_symbol_object_with_docstring_context(
        symbol_object=symbol_object,
        modifiers=modifiers,
        doc_objects=doc_objects,
    )

    if len(result) < 2:
        for token in doc_objects:
            _append_distinct_token(result, token)

    return result


def _enrich_symbol_object_with_docstring_context(
    symbol_object: list[str],
    modifiers: list[str],
    doc_objects: list[str],
) -> list[str]:
    """Merge symbol object, docstring modifiers, and docstring context deterministically."""

    result: list[str] = []
    terminal_tokens = [token for token in symbol_object if token in _BLENDED_TERMINAL_KIND_TOKENS]
    symbol_core = [token for token in symbol_object if token not in terminal_tokens]
    doc_context = [
        token
        for token in doc_objects
        if token not in set(symbol_object)
        and token not in set(modifiers)
        and token not in _BLENDED_TERMINAL_KIND_TOKENS
    ]

    if terminal_tokens and doc_context:
        for token in modifiers + doc_context[:1] + symbol_core + terminal_tokens[:1]:
            _append_distinct_token(result, token)
        return result

    for token in modifiers + symbol_object:
        _append_distinct_token(result, token)
    return result


def _build_lock_object_tokens(facts: _NormalizedFacts) -> list[str]:
    """Build an object phrase for protected lock/write contexts."""

    base_tokens = [
        token
        for token in facts.symbol_tokens
        if token not in {"error", "exception", "locked", "lock"}
    ]
    if not base_tokens:
        base_tokens = [
            token
            for token in facts.docstring_tokens
            if _is_functional_blended_token(token)
            and token not in {"protected", "locked", "lock", "error", "exception"}
        ][:2]
    operation_tokens = [
        token
        for token in facts.docstring_tokens
        if token in _BLENDED_OPERATION_TOKENS
    ]
    result: list[str] = []
    for token in base_tokens[:2] + operation_tokens[:1] + ["lock"]:
        _append_distinct_token(result, token)
    return result


def _docstring_modifier_tokens(facts: _NormalizedFacts) -> list[str]:
    """Return docstring modifiers that enrich the symbol object."""

    result: list[str] = []
    symbol_token_set = set(facts.symbol_tokens)
    for token in facts.docstring_tokens:
        if token in symbol_token_set:
            continue
        if token in _BLENDED_STATE_TOKENS:
            _append_distinct_token(result, token)
    return result[:2]


def _docstring_object_tokens(facts: _NormalizedFacts, include_operation: bool) -> list[str]:
    """Return object-like tokens from docstring evidence."""

    result: list[str] = []
    for token in facts.docstring_tokens:
        if token in _BLENDED_GLUE_TOKENS or token in _BLENDED_PROCEDURAL_TOKENS:
            continue
        if token in _BLENDED_ACTIONS:
            continue
        if token in _BLENDED_KIND_TOKENS:
            continue
        if token in _BLENDED_OPERATION_TOKENS and not include_operation:
            continue
        _append_distinct_token(result, token)
    return result


def _object_tokens_from_blended_tokens(tokens: list[str]) -> list[str]:
    """Return object tokens after removing actions, glue, and weak kind words."""

    result: list[str] = []
    for token in tokens:
        if token in _BLENDED_ACTIONS:
            continue
        if token in _BLENDED_GLUE_TOKENS or token in _BLENDED_PROCEDURAL_TOKENS:
            continue
        if token in _BLENDED_KIND_TOKENS:
            continue
        _append_distinct_token(result, token)
    return result


def _append_distinct_token(tokens: list[str], token: str) -> None:
    """Append one token if it is non-empty and absent."""

    if token and token not in tokens:
        tokens.append(token)


def _is_functional_blended_token(token: str) -> bool:
    """Return True when a token can identify the current code block."""

    return (
        token not in _BLENDED_ACTIONS
        and token not in _BLENDED_GLUE_TOKENS
        and token not in _BLENDED_PROCEDURAL_TOKENS
        and token not in _BLENDED_KIND_TOKENS
        and len(token) >= 3
    )


def _has_token(tokens: tuple[str, ...], expected: str) -> bool:
    """Return True when normalized tokens contain the expected token."""

    return expected in tokens


def _has_any_token(tokens: tuple[str, ...], expected_tokens: set[str]) -> bool:
    """Return True when normalized tokens contain any expected token."""

    return any(token in expected_tokens for token in tokens)

def _infer_action_from_tokens(tokens: tuple[str, ...]) -> str | None:
    """Infer an action verb from ordered tokens."""

    action_map = {
        "verify": "Verify",
        "validate": "Validate",
        "scan": "Scan",
        "load": "Load",
        "save": "Save",
        "write": "Write",
        "resolve": "Resolve",
        "collect": "Collect",
        "compose": "Compose",
        "suggest": "Suggest",
        "build": "Build",
        "create": "Create",
        "detect": "Detect",
        "parse": "Parse",
        "render": "Render",
        "protect": "Protect",
        "lock": "Lock",
        "handle": "Handle",
        "issue": "Issue",
        "convert": "Convert",
        "normalize": "Normalize",
    }
    for token in tokens:
        if token in action_map:
            return action_map[token]
    return None


def _merge_distinct_tokens(tokens: list[str]) -> list[str]:
    """Return ordered distinct tokens, skipping filler words."""

    ignored = {"when", "while", "with", "from", "that", "this", "is", "are", "was", "were", "the", "a", "an"}
    result: list[str] = []
    for token in tokens:
        if token in ignored or token in result:
            continue
        result.append(token)
    return result
