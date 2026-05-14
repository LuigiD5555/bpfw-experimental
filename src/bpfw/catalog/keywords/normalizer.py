"""Normalizer for cleaning and standardizing tokens."""


def normalize_token(token: str) -> str:
    """
    Normalize one token for deterministic ranking.

    Applies plural-to-singular conversion and other normalizations.

    Args:
        token: Token to normalize.

    Returns:
        Normalized token.
    """
    if not token:
        return token

    lowered = token.lower()

    # Plural to singular: common patterns
    if len(lowered) > 4 and lowered.endswith("ies"):
        return f"{lowered[:-3]}y"
    if (
        len(lowered) > 3
        and lowered.endswith("es")
        and (
            lowered.endswith(("ses", "xes", "zes"))
            or lowered.endswith(("ches", "shes"))
        )
    ):
        return lowered[:-2]
    if len(lowered) > 3 and lowered.endswith("s"):
        return lowered[:-1]

    return lowered


def filter_noise_tokens(tokens: list[str]) -> list[str]:
    """
    Filter out noise tokens that provide little value.

    This uses structural rules rather than hardcoded vocabulary.

    Args:
        tokens: List of tokens to filter.

    Returns:
        Filtered list of tokens.
    """
    filtered = []

    for token in tokens:
        # Skip tokens that are too short
        if len(token) < 2:
            continue

        # Skip tokens that are just numbers
        if token.isdigit():
            continue

        # Skip single-character tokens (except 'x' which is common in coordinates)
        if len(token) == 1 and token not in {"x", "y", "z"}:
            continue

        # Skip common programming patterns
        if token in {"self", "cls", "args", "kwargs", "this", "that"}:
            continue

        filtered.append(token)

    return filtered


def deduplicate_tokens(tokens: list[str]) -> list[str]:
    """
    Remove duplicate tokens while preserving order.

    Args:
        tokens: List of tokens to deduplicate.

    Returns:
        Deduplicated list of tokens.
    """
    seen = set()
    deduplicated = []

    for token in tokens:
        if token not in seen:
            seen.add(token)
            deduplicated.append(token)

    return deduplicated


def normalize_tokens(tokens: list[str]) -> list[str]:
    """
    Normalize and clean a list of tokens.

    Args:
        tokens: List of tokens to normalize.

    Returns:
        Normalized and filtered list of tokens.
    """
    if not tokens:
        return []

    # Normalize each token
    normalized = [normalize_token(token) for token in tokens]

    # Filter noise
    filtered = filter_noise_tokens(normalized)

    # Deduplicate
    deduplicated = deduplicate_tokens(filtered)

    return deduplicated


def build_phrases_from_tokens(tokens: list[str], max_length: int = 4) -> list[str]:
    """
    Build phrases from consecutive tokens.

    This is useful for capturing multi-word concepts like
    "blueprint authority" or "bank transactions".

    Args:
        tokens: List of tokens.
        max_length: Maximum phrase length.

    Returns:
        List of phrases (space-separated tokens).
    """
    if not tokens:
        return []

    phrases = []

    for length in range(2, min(max_length + 1, len(tokens) + 1)):
        for i in range(len(tokens) - length + 1):
            phrase = " ".join(tokens[i:i + length])
            phrases.append(phrase)

    return phrases
