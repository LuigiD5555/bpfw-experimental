"""Extract keywords from code blocks."""

from typing import Any

from bpfw.catalog.keywords.evidence import extract_evidence_from_block
from bpfw.catalog.keywords.models import BlockKeywordProfile, KeywordCandidate, ProjectVocabulary
from bpfw.catalog.keywords.normalizer import build_phrases_from_tokens, normalize_tokens
from bpfw.catalog.keywords.scorer import deduplicate_similar, score_evidence
from bpfw.catalog.keywords.tokenizer import tokenize_identifier


def extract_block_keywords(
    block: dict[str, Any],
    vocabulary: "ProjectVocabulary | None" = None,
    max_keywords: int = 15,
    max_phrases: int = 10,
) -> BlockKeywordProfile:
    """
    Extract ranked keywords from a single code block.

    Args:
        block: Block dictionary from scanner.
        vocabulary: Optional ProjectVocabulary for global context.
        max_keywords: Maximum number of keywords to return.
        max_phrases: Maximum number of phrases to return.

    Returns:
        BlockKeywordProfile with ranked keywords and phrases.
    """
    # Get block ID
    block_id = block.get("symbol", block.get("name", "unknown"))

    # Extract evidence from block
    evidence = extract_evidence_from_block(block)

    # Score and rank candidates
    candidates = score_evidence(evidence, vocabulary=vocabulary)

    # Deduplicate similar candidates
    candidates = deduplicate_similar(candidates)

    # Limit to top keywords
    keywords = candidates[:max_keywords]

    # Build phrases from top keywords
    phrases = _build_phrases_from_block(block, keywords, max_phrases)

    return BlockKeywordProfile(
        block_id=block_id,
        keywords=keywords,
        phrases=phrases,
    )


def _build_phrases_from_block(
    block: dict[str, Any],
    keywords: list[KeywordCandidate],
    max_phrases: int,
) -> list[str]:
    """
    Build phrases from block evidence.

    This extracts meaningful phrases from:
    - Symbol name (e.g., "blueprint authority")
    - Docstring summary
    - Top keywords

    Args:
        block: Block dictionary from scanner.
        keywords: Ranked keyword candidates.
        max_phrases: Maximum number of phrases to return.

    Returns:
        List of phrases.
    """
    phrases: list[str] = []

    # Get symbol name tokens
    symbol = block.get("symbol", "")
    if symbol:
        simple_name = symbol.split(".")[-1] if "." in symbol else symbol
        symbol_tokens = tokenize_identifier(simple_name)
        if len(symbol_tokens) >= 2:
            # Build phrases from symbol tokens
            symbol_phrases = build_phrases_from_tokens(symbol_tokens, max_length=4)
            phrases.extend(symbol_phrases[:5])

    # Get docstring summary tokens
    detected = block.get("detected", {})
    if isinstance(detected, dict):
        docstring = detected.get("docstring", "")
        if docstring:
            summary = docstring.split(".")[0]
            from bpfw.catalog.keywords.tokenizer import tokenize_text
            doc_tokens = normalize_tokens(tokenize_text(summary))
            if len(doc_tokens) >= 2:
                # Build phrases from docstring tokens
                doc_phrases = build_phrases_from_tokens(doc_tokens, max_length=3)
                phrases.extend(doc_phrases[:5])

    # Build phrases from top keywords
    top_tokens = [k.token for k in keywords[:10]]
    if len(top_tokens) >= 2:
        keyword_phrases = build_phrases_from_tokens(top_tokens, max_length=3)
        phrases.extend(keyword_phrases[:5])

    # Deduplicate and limit
    seen = set()
    unique_phrases = []
    for phrase in phrases:
        if phrase not in seen:
            seen.add(phrase)
            unique_phrases.append(phrase)

    return unique_phrases[:max_phrases]