"""PURPOSE domain-specific tokenization helpers
DOMAIN  domain suggestions
"""

import re


def tokenize_identifier(text: str) -> list[str]:
    """PURPOSE split identifier text into clean terms into words
    DOMAIN  domain suggestions
    """

    if not isinstance(text, str):
        return []
    return [token.lower() for token in re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|_|\b)|[A-Z]?[a-z]+|\d+", text.replace('.', '_'))]
