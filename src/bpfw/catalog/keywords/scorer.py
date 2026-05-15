"""Scoring for keyword candidates."""

from collections import defaultdict

from bpfw.catalog.keywords.models import KeywordCandidate, KeywordEvidence, ProjectVocabulary
from bpfw.catalog.keywords.normalizer import normalize_tokens


def score_evidence(
    evidence: list[KeywordEvidence],
    vocabulary: ProjectVocabulary | None = None,
) -> list[KeywordCandidate]:
    """
    Evaluate and order keyword candidates from evidence.

    Args:
        evidence: List of KeywordEvidence items.
        vocabulary: Optional ProjectVocabulary for global context.

    Returns:
        List of ordered KeywordCandidate items.
    """
    if not evidence:
        return []

    # Group evidence by normalized token
    token_scores: dict[str, float] = defaultdict(float)
    token_sources: dict[str, list[str]] = defaultdict(list)
    token_occurrences: dict[str, int] = defaultdict(int)

    for item in evidence:
        # Normalize the token
        normalized_tokens = normalize_tokens([item.raw_text])

        for token in normalized_tokens:
            # Accumulate score
            token_scores[token] += item.weight
            token_sources[token].append(item.source)
            token_occurrences[token] += 1

    # Adjust scores based on vocabulary
    if vocabulary:
        for token in list(token_scores.keys()):
            local_score = token_scores[token]

            # Apply distinctiveness factor
            distinctiveness = compute_distinctiveness(token, vocabulary)

            # Adjust score: boost rare tokens, penalize common tokens
            adjusted_score = local_score * distinctiveness

            # Additional penalty for extremely common tokens
            if vocabulary.is_common_token(token, threshold=0.7):
                adjusted_score *= 0.5

            token_scores[token] = adjusted_score

    # Create candidate objects
    candidates = [
        KeywordCandidate(
            token=token,
            score=score,
            sources=list(set(token_sources[token])),
            occurrences=token_occurrences[token],
        )
        for token, score in token_scores.items()
    ]

    # Sort by score (descending)
    candidates.sort(key=lambda c: c.score, reverse=True)

    return candidates


def compute_distinctiveness(
    token: str,
    vocabulary: ProjectVocabulary,
) -> float:
    """
    Compute how distinctive a token is in the project.

    Rare tokens get a boost (> 1.0), common tokens get a penalty (< 1.0).

    Args:
        token: Token to evaluate.
        vocabulary: Project vocabulary statistics.

    Returns:
        Distinctiveness factor (typically 0.5 to 1.5).
    """
    block_frequency = vocabulary.get_token_block_frequency(token)

    # Very rare token (appears in < 10% of blocks)
    if block_frequency < 0.1:
        return 1.5

    # Rare token (appears in 10-30% of blocks)
    if block_frequency < 0.3:
        return 1.2

    # Normal token (appears in 30-50% of blocks)
    if block_frequency < 0.5:
        return 1.0

    # Common token (appears in 50-70% of blocks)
    if block_frequency < 0.7:
        return 0.8

    # Very common token (appears in > 70% of blocks)
    return 0.6


def get_confidence_level(
    candidate: KeywordCandidate,
    vocabulary: ProjectVocabulary | None = None,
) -> str:
    """
    Determine confidence level for a keyword candidate.

    Confidence is based on:
    - Score magnitude
    - Number of sources
    - Block frequency (if vocabulary available)

    Args:
        candidate: KeywordCandidate to evaluate.
        vocabulary: Optional ProjectVocabulary for context.

    Returns:
        Confidence level: "high", "medium", or "low".
    """
    # High confidence: high score from multiple strong sources
    if candidate.score >= 15.0 and len(candidate.sources) >= 2:
        if vocabulary and vocabulary.is_common_token(candidate.token, threshold=0.7):
            return "medium"
        return "high"

    # Medium confidence: moderate score or single strong source
    if candidate.score >= 8.0:
        return "medium"

    # Low confidence: weak evidence
    return "low"


def filter_low_confidence(
    candidates: list[KeywordCandidate],
    vocabulary: ProjectVocabulary | None = None,
    min_confidence: str = "low",
) -> list[KeywordCandidate]:
    """
    Filter candidates by confidence level.

    Args:
        candidates: List of KeywordCandidate items.
        vocabulary: Optional ProjectVocabulary for context.
        min_confidence: Minimum confidence level ("low", "medium", "high").

    Returns:
        Filtered list of candidates.
    """
    confidence_order = {"low": 0, "medium": 1, "high": 2}
    min_level = confidence_order.get(min_confidence, 0)

    return [
        candidate
        for candidate in candidates
        if confidence_order.get(get_confidence_level(candidate, vocabulary), 0) >= min_level
    ]


def deduplicate_similar(
    candidates: list[KeywordCandidate],
    similarity_threshold: int = 2,
) -> list[KeywordCandidate]:
    """
    Deduplicate candidates with similar tokens.

    This handles cases where we have both singular and plural forms
    of the same concept.

    Args:
        candidates: List of KeywordCandidate items.
        similarity_threshold: Edit distance threshold for similarity.

    Returns:
        Deduplicated list of candidates.
    """
    if len(candidates) <= 1:
        return candidates

    kept = []
    for candidate in candidates:
        # Check if similar to any already kept candidate
        is_duplicate = False
        for kept_candidate in kept:
            if tokens_similar(candidate.token, kept_candidate.token, similarity_threshold):
                # Keep the one with higher score
                if candidate.score > kept_candidate.score:
                    # Replace the lower-scored candidate
                    kept[kept.index(kept_candidate)] = candidate
                is_duplicate = True
                break

        if not is_duplicate:
            kept.append(candidate)

    return kept


def tokens_similar(token1: str, token2: str, threshold: int = 2) -> bool:
    """
    Check if two tokens are similar (likely variations of the same word).

    Args:
        token1: First token.
        token2: Second token.
        threshold: Edit distance threshold.

    Returns:
        True if tokens are similar.
    """
    if token1 == token2:
        return True

    # Check if one is a substring of the other
    if token1 in token2 or token2 in token1:
        return True

    # Simple edit distance
    if edit_distance(token1, token2) <= threshold:
        return True

    return False


def edit_distance(s1: str, s2: str) -> int:
    """
    Compute Levenshtein edit distance between two strings.

    Args:
        s1: First string.
        s2: Second string.

    Returns:
        Edit distance.
    """
    if len(s1) < len(s2):
        return edit_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]