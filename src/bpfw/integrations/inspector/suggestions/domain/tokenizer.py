"""Domain-specific tokenization helpers."""

import re


def tokenize_identifier(text: str) -> list[str]:
    """Tokenize identifier text into normalized terms.

    Args:
        text: Raw identifier text.

    Returns:
        Ordered lowercased token list.
    """

    if not isinstance(text, str):
        return []
    return [token.lower() for token in re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|_|\b)|[A-Z]?[a-z]+|\d+", text.replace('.', '_'))]
